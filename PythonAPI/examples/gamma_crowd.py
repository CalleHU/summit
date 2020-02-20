#!/usr/bin/env python

import glob
import os
import sys

try:
    sys.path.append(glob.glob(os.path.abspath('%s/../../carla/dist/carla-*%d.%d-%s.egg' % (
        os.path.realpath(__file__),
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64')))[0])
except IndexError:
    pass

from collections import defaultdict
from multiprocessing import Process
from threading import RLock
import Pyro4
import argparse
import carla
import math
import numpy as np
import random
import time
if sys.version_info.major == 2:
    from pathlib2 import Path
else:
    from pathlib import Path



''' ========== CONSTANTS ========== '''
DATA_PATH = Path(os.path.realpath(__file__)).parent.parent.parent/'Data'
PATH_MIN_POINTS = 20
PATH_INTERVAL = 1.0

CAR_SPEED_KP = 1.5
CAR_SPEED_KI = 0.5
CAR_SPEED_KD = 0.005
CAR_STEER_KP = 2.5

BIKE_SPEED_KP = 0.8
BIKE_SPEED_KI = 0.2
BIKE_SPEED_KD = 0.0
BIKE_STEER_KP = 2.5

Pyro4.config.COMMTIMEOUT = 2.0
Pyro4.config.SERIALIZERS_ACCEPTED.add('serpent')
Pyro4.config.SERIALIZER = 'serpent'
Pyro4.util.SerializerBase.register_class_to_dict(
        carla.Vector2D, 
        lambda o: { 
            '__class__': 'carla.Vector2D',
            'x': o.x,
            'y': o.y
        })
Pyro4.util.SerializerBase.register_dict_to_class(
        'carla.Vector2D',
        lambda c, o: carla.Vector2D(o['x'], o['y']))
Pyro4.util.SerializerBase.register_class_to_dict(
        carla.SumoNetworkRoutePoint, 	
        lambda o: { 	
            '__class__': 'carla.SumoNetworkRoutePoint',	
            'edge': o.edge,	
            'lane': o.lane,	
            'segment': o.segment,	
            'offset': o.offset	
        })
def dict_to_sumo_network_route_point(c, o):	
    r = carla.SumoNetworkRoutePoint()	
    r.edge = str(o['edge']) # In python2, this is a unicode, so use str() to convert.
    r.lane = o['lane']	
    r.segment = o['segment']	
    r.offset = o['offset']	
    return r	
Pyro4.util.SerializerBase.register_dict_to_class(	
        'carla.SumoNetworkRoutePoint', dict_to_sumo_network_route_point)	
Pyro4.util.SerializerBase.register_class_to_dict(	
        carla.SidewalkRoutePoint, 	
        lambda o: { 	
            '__class__': 'carla.SidewalkRoutePoint',	
            'polygon_id': o.polygon_id,	
            'segment_id': o.segment_id,	
            'offset': o.offset	
        })	
def dict_to_sidewalk_route_point(c, o):	
    r = carla.SidewalkRoutePoint()	
    r.polygon_id = o['polygon_id']	
    r.segment_id = o['segment_id']	
    r.offset = o['offset']
    return r	
Pyro4.util.SerializerBase.register_dict_to_class(	
        'carla.SidewalkRoutePoint', dict_to_sidewalk_route_point)



''' ========== MESSAGE PASSING SERVICE ========== '''
@Pyro4.expose
@Pyro4.behavior(instance_mode="single")
class CrowdService():
    def __init__(self):
        self._control_velocities = []
        self._control_velocities_lock = RLock()

        self._local_intentions = []
        self._local_intentions_lock = RLock()
   
    @property
    def control_velocities(self):
        return self._control_velocities

    @control_velocities.setter
    def control_velocities(self, velocities):
        self._control_velocities = velocities

    def acquire_control_velocities(self):
        self._control_velocities_lock.acquire()

    def release_control_velocities(self):
        self._control_velocities_lock.release()
    
    @property
    def local_intentions(self):
        return self._local_intentions

    @local_intentions.setter
    def local_intentions(self, velocities):
        self._local_intentions = velocities

    def acquire_local_intentions(self):
        self._local_intentions_lock.acquire()

    def release_local_intentions(self):
        self._local_intentions_lock.release()



''' ========== UTILITY FUNCTIONS AND CLASSES ========== '''
def get_signed_angle_diff(vector1, vector2):
    theta = math.atan2(vector1.y, vector1.x) - math.atan2(vector2.y, vector2.x)
    theta = np.rad2deg(theta)
    if theta > 180:
        theta -= 360
    elif theta < -180:
        theta += 360
    return theta

def get_steer_angle_range(actor):
    actor_physics_control = actor.get_physics_control()
    return (actor_physics_control.wheels[0].max_steer_angle + actor_physics_control.wheels[1].max_steer_angle) / 2

def get_position(actor):
    pos3d = actor.get_location()
    return carla.Vector2D(pos3d.x, pos3d.y)

def get_forward_direction(actor):
    forward = actor.get_transform().get_forward_vector()
    return carla.Vector2D(forward.x, forward.y)

def get_bounding_box(actor):
    return actor.bounding_box

def get_position_3d(actor):
    return actor.get_location()

def get_aabb(actor):
    bbox = actor.bounding_box
    loc = carla.Vector2D(bbox.location.x, bbox.location.y) + get_position(actor)
    forward_vec = get_forward_direction(actor).make_unit_vector()
    sideward_vec = forward_vec.rotate(np.deg2rad(90))
    corners = [loc - bbox.extent.x * forward_vec + bbox.extent.y * sideward_vec,
               loc + bbox.extent.x * forward_vec + bbox.extent.y * sideward_vec,
               loc + bbox.extent.x * forward_vec - bbox.extent.y * sideward_vec,
               loc - bbox.extent.x * forward_vec - bbox.extent.y * sideward_vec]
    return carla.AABB2D(
        carla.Vector2D(
            min(v.x for v in corners),
            min(v.y for v in corners)),
        carla.Vector2D(
            max(v.x for v in corners),
            max(v.y for v in corners)))

def get_velocity(actor):
    v = actor.get_velocity()
    return carla.Vector2D(v.x, v.y)
    
def get_vehicle_bounding_box_corners(actor):
    bbox = actor.bounding_box
    loc = carla.Vector2D(bbox.location.x, bbox.location.y) + get_position(actor)
    forward_vec = get_forward_direction(actor).make_unit_vector()
    sideward_vec = forward_vec.rotate(np.deg2rad(90))
    half_y_len = bbox.extent.y + 0.3
    half_x_len_forward = bbox.extent.x + 1.0
    half_x_len_backward = bbox.extent.x + 0.1
    corners = [loc - half_x_len_backward * forward_vec + half_y_len * sideward_vec,
               loc + half_x_len_forward * forward_vec + half_y_len * sideward_vec,
               loc + half_x_len_forward * forward_vec - half_y_len * sideward_vec,
               loc - half_x_len_backward * forward_vec - half_y_len * sideward_vec]
    return corners

def get_pedestrian_bounding_box_corners(actor):
    bbox = actor.bounding_box
    loc = carla.Vector2D(bbox.location.x, bbox.location.y) + get_position(actor)
    forward_vec = get_forward_direction(actor).make_unit_vector()
    sideward_vec = forward_vec.rotate(np.deg2rad(90))
    # Hardcoded values for pedestrians.
    half_y_len = 0.25
    half_x_len = 0.25
    corners = [loc - half_x_len * forward_vec + half_y_len * sideward_vec,
               loc + half_x_len * forward_vec + half_y_len * sideward_vec,
               loc + half_x_len * forward_vec - half_y_len * sideward_vec,
               loc - half_x_len * forward_vec - half_y_len * sideward_vec]
    return corners
    
def get_lane_constraints(sidewalk, position, forward_vec):
    left_line_end = position + (1.5 + 2.0 + 0.8) * ((forward_vec.rotate(np.deg2rad(-90))).make_unit_vector())
    right_line_end = position + (1.5 + 2.0 + 0.8) * ((forward_vec.rotate(np.deg2rad(90))).make_unit_vector())
    left_lane_constrained_by_sidewalk = sidewalk.intersects(carla.Segment2D(position, left_line_end))
    right_lane_constrained_by_sidewalk = sidewalk.intersects(carla.Segment2D(position, right_line_end))
    return left_lane_constrained_by_sidewalk, right_lane_constrained_by_sidewalk

class SumoNetworkAgentPath:
    def __init__(self, route_points, min_points, interval):
        self.route_points = route_points
        self.min_points = min_points
        self.interval = interval

    @staticmethod
    def rand_path(sumo_network, min_points, interval, segment_map, rng=random):
        spawn_point = None
        route_paths = None
        while not spawn_point or len(route_paths) < 1:
            spawn_point = segment_map.rand_point()
            spawn_point = sumo_network.get_nearest_route_point(spawn_point)
            route_paths = sumo_network.get_next_route_paths(spawn_point, min_points - 1, interval)

        return SumoNetworkAgentPath(rng.choice(route_paths), min_points, interval)

    def resize(self, sumo_network, rng=random):
        while len(self.route_points) < self.min_points:
            next_points = sumo_network.get_next_route_points(self.route_points[-1], self.interval)
            if len(next_points) == 0:
                return False
            self.route_points.append(rng.choice(next_points))
        return True

    def get_min_offset(self, sumo_network, position):
        min_offset = None
        for i in range(int(len(self.route_points) / 2)):
            route_point = self.route_points[i]
            offset = position - sumo_network.get_route_point_position(route_point)
            offset = offset.length() 
            if min_offset == None or offset < min_offset:
                min_offset = offset
        return min_offset

    def cut(self, sumo_network, position):
        cut_index = 0
        min_offset = None
        min_offset_index = None
        for i in range(int(len(self.route_points) / 2)):
            route_point = self.route_points[i]
            offset = position - sumo_network.get_route_point_position(route_point)
            offset = offset.length() 
            if min_offset == None or offset < min_offset:
                min_offset = offset
                min_offset_index = i
            if offset <= 1.0:
                cut_index = i + 1

        # Invalid path because too far away.
        if min_offset > 1.0:
            self.route_points = self.route_points[min_offset_index:]
        else:
            self.route_points = self.route_points[cut_index:]

    def get_position(self, sumo_network, index=0):
        return sumo_network.get_route_point_position(self.route_points[index])

    def get_yaw(self, sumo_network, index=0):
        pos = sumo_network.get_route_point_position(self.route_points[index])
        next_pos = sumo_network.get_route_point_position(self.route_points[index + 1])
        return np.rad2deg(math.atan2(next_pos.y - pos.y, next_pos.x - pos.x))

class SidewalkAgentPath:
    def __init__(self, route_points, route_orientations, min_points, interval):
        self.min_points = min_points
        self.interval = interval
        self.route_points = route_points
        self.route_orientations = route_orientations

    @staticmethod
    def rand_path(sidewalk, min_points, interval, cross_probability, segment_map, rng=None):
        if rng is None:
            rng = random
    
        spawn_point = sidewalk.get_nearest_route_point(segment_map.rand_point())

        path = SidewalkAgentPath([spawn_point], [rng.choice([True, False])], min_points, interval)
        path.resize(sidewalk, cross_probability)
        return path

    def resize(self, sidewalk, cross_probability, rng=None):
        if rng is None:
            rng = random

        while len(self.route_points) < self.min_points:
            if rng.random() <= cross_probability:
                adjacent_route_point = sidewalk.get_adjacent_route_point(self.route_points[-1], 50.0)
                if adjacent_route_point is not None:
                    self.route_points.append(adjacent_route_point)
                    self.route_orientations.append(rng.randint(0, 1) == 1)
                    continue

            if self.route_orientations[-1]:
                self.route_points.append(
                        sidewalk.get_next_route_point(self.route_points[-1], self.interval))
                self.route_orientations.append(True)
            else:
                self.route_points.append(
                        sidewalk.get_previous_route_point(self.route_points[-1], self.interval))
                self.route_orientations.append(False)

        return True

    def cut(self, sidewalk, position):
        cut_index = 0
        min_offset = None
        min_offset_index = None
        for i in range(int(len(self.route_points) / 2)):
            route_point = self.route_points[i]
            offset = position - sidewalk.get_route_point_position(route_point)
            offset = offset.length()
            if min_offset is None or offset < min_offset:
                min_offset = offset
                min_offset_index = i
            if offset <= 1.0:
                cut_index = i + 1
        
        # Invalid path because too far away.
        if min_offset > 1.0:
            self.route_points = self.route_points[min_offset_index:]
            self.route_orientations = self.route_orientations[min_offset_index:]
        else:
            self.route_points = self.route_points[cut_index:]
            self.route_orientations = self.route_orientations[cut_index:]

    def get_position(self, sidewalk, index=0):
        return sidewalk.get_route_point_position(self.route_points[index])

    def get_yaw(self, sidewalk, index=0):
        pos = sidewalk.get_route_point_position(self.route_points[index])
        next_pos = sidewalk.get_route_point_position(self.route_points[index + 1])
        return np.rad2deg(math.atan2(next_pos.y - pos.y, next_pos.x - pos.x))

class Agent(object):
    def __init__(self, actor_id, type_tag, path, preferred_speed, steer_angle_range=0.0):
        self.actor_id = actor_id
        self.type_tag = type_tag
        self.path = path
        self.preferred_speed = preferred_speed
        self.stuck_time = None
        self.control_velocity = carla.Vector2D(0, 0)
        self.steer_angle_range = steer_angle_range

class Context(object):
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)

        with (DATA_PATH/'{}.sim_bounds'.format(args.dataset)).open('r') as f:
            self.bounds_min = carla.Vector2D(*[float(v) for v in f.readline().split(',')])
            self.bounds_max = carla.Vector2D(*[float(v) for v in f.readline().split(',')])
            self.bounds_occupancy = carla.OccupancyMap(self.bounds_min, self.bounds_max)

        self.sumo_network = carla.SumoNetwork.load(str(DATA_PATH/'{}.net.xml'.format(args.dataset)))
        self.sumo_network_segments = self.sumo_network.create_segment_map()
        self.sumo_network_spawn_segments = self.sumo_network_segments.intersection(carla.OccupancyMap(self.bounds_min, self.bounds_max))
        self.sumo_network_spawn_segments.seed_rand(self.rng.getrandbits(32))
        self.sumo_network_occupancy = carla.OccupancyMap.load(str(DATA_PATH/'{}.network.wkt'.format(args.dataset)))

        self.sidewalk = self.sumo_network_occupancy.create_sidewalk(1.5)
        self.sidewalk_segments = self.sidewalk.create_segment_map()
        self.sidewalk_spawn_segments = self.sidewalk_segments.intersection(carla.OccupancyMap(self.bounds_min, self.bounds_max))
        self.sidewalk_spawn_segments.seed_rand(self.rng.getrandbits(32))
        self.sidewalk_occupancy = carla.OccupancyMap.load(str(DATA_PATH/'{}.sidewalk.wkt'.format(args.dataset)))

        self.client = carla.Client(args.host, args.port)
        self.client.set_timeout(10.0)
        self.world = self.client.get_world()
        self.crowd_service = Pyro4.Proxy('PYRO:crowdservice.warehouse@localhost:8100')
    
        self.pedestrian_blueprints = self.world.get_blueprint_library().filter('walker.pedestrian.*')
        self.vehicle_blueprints = self.world.get_blueprint_library().filter('vehicle.*')
        self.car_blueprints = [x for x in self.vehicle_blueprints if int(x.get_attribute('number_of_wheels')) == 4]
        self.car_blueprints = [x for x in self.car_blueprints if x.id not in ['vehicle.bmw.isetta']] # This dude moves too slow.
        self.bike_blueprints = [x for x in self.vehicle_blueprints if int(x.get_attribute('number_of_wheels')) == 2]



''' ========== MAIN LOGIC FUNCTIONS ========== '''
def do_destroy(c, car_agents, bike_agents, pedestrian_agents):
   
    update_time = time.time()

    commands = []
    for agents in [car_agents, bike_agents, pedestrian_agents]:
        next_agents = []
        for agent in agents:
            actor = c.world.get_actor(agent.actor_id)
            delete = False
            if not delete and not c.bounds_occupancy.contains(get_position(actor)):
                delete = True
            if not delete and get_position_3d(actor).z < -10:
                delete = True
            if not delete and \
                    ((agent.type_tag in ['Car', 'Bicycle']) and not c.sumo_network_occupancy.contains(get_position(actor))):
                delete = True
            if get_velocity(actor).length() < c.args.stuck_speed:
                if agent.stuck_time is not None:
                    if update_time - agent.stuck_time >= c.args.stuck_duration:
                        delete = True
                else:
                    agent.stuck_time = update_time
            else:
                agent.stuck_time = None
            
            if delete:
                commands.append(carla.command.DestroyActor(agent.actor_id))
            else:
                next_agents.append(agent)
        agents[:] = next_agents

    c.client.apply_batch_sync(commands)
    c.world.wait_for_tick()

def do_spawn(c, car_agents, bike_agents, pedestrian_agents):

    # Get AABB.
    aabbs = []
    for actor in c.world.get_actors():
        if isinstance(actor, carla.Vehicle) or isinstance(actor, carla.Walker):
            aabbs.append(get_aabb(actor))
    aabb_map = carla.AABBMap(aabbs)

    # Spawn at most one car.
    if len(car_agents) < c.args.num_car:
        path = SumoNetworkAgentPath.rand_path(c.sumo_network, PATH_MIN_POINTS, PATH_INTERVAL, c.sumo_network_spawn_segments, rng=c.rng)
        if not aabb_map.intersects(carla.AABB2D(
                carla.Vector2D(path.get_position(c.sumo_network, 0).x - c.args.clearance_car,
                               path.get_position(c.sumo_network, 0).y - c.args.clearance_car),
                carla.Vector2D(path.get_position(c.sumo_network, 0).x + c.args.clearance_car,
                               path.get_position(c.sumo_network, 0).y + c.args.clearance_car))):
            trans = carla.Transform()
            trans.location.x = path.get_position(c.sumo_network, 0).x
            trans.location.y = path.get_position(c.sumo_network, 0).y
            trans.location.z = 0.2
            trans.rotation.yaw = path.get_yaw(c.sumo_network, 0)

            actor = c.world.try_spawn_actor(c.rng.choice(c.car_blueprints), trans)
            c.world.wait_for_tick(1.0) # Without this, the actor list gets messed up in CARLA, leading to random actors spawning.
            if actor:
                actor.set_collision_enabled(c.args.collision)
                c.world.wait_for_tick(1.0)  # For actor to update pos and bounds, and for collision to apply.
                aabb_map.insert(get_aabb(actor))
                car_agents.append(Agent(
                    actor.id, 'Car', path, 5.0 + c.rng.uniform(-0.5, 0.5),
                    get_steer_angle_range(actor)))


    # Spawn at most one bike.
    if len(bike_agents) < c.args.num_bike:
        path = SumoNetworkAgentPath.rand_path(c.sumo_network, PATH_MIN_POINTS, PATH_INTERVAL, c.sumo_network_spawn_segments, rng=c.rng)
        if not aabb_map.intersects(carla.AABB2D(
                carla.Vector2D(path.get_position(c.sumo_network, 0).x - c.args.clearance_bike,
                               path.get_position(c.sumo_network, 0).y - c.args.clearance_bike),
                carla.Vector2D(path.get_position(c.sumo_network, 0).x + c.args.clearance_bike,
                               path.get_position(c.sumo_network, 0).y + c.args.clearance_bike))):
            trans = carla.Transform()
            trans.location.x = path.get_position(c.sumo_network, 0).x
            trans.location.y = path.get_position(c.sumo_network, 0).y
            trans.location.z = 0.2
            trans.rotation.yaw = path.get_yaw(c.sumo_network, 0)

            actor = c.world.try_spawn_actor(c.rng.choice(c.bike_blueprints), trans)
            c.world.wait_for_tick(1.0) # Without this, the actor list gets messed up in CARLA, leading to random actors spawning.
            if actor:
                actor.set_collision_enabled(c.args.collision)
                c.world.wait_for_tick(1.0)  # For actor to update pos and bounds, and for collision to apply.
                aabb_map.insert(get_aabb(actor))
                bike_agents.append(Agent(
                    actor.id, 'Bicycle', path, 3.0 + c.rng.uniform(-0.5, 0.5),
                    get_steer_angle_range(actor)))


    # Spawn at most one pedestrian.
    if len(pedestrian_agents) < c.args.num_pedestrian:
        path = SidewalkAgentPath.rand_path(c.sidewalk, PATH_MIN_POINTS, PATH_INTERVAL, c.args.cross_probability, c.sidewalk_spawn_segments, c.rng)
        if not aabb_map.intersects(carla.AABB2D(
                carla.Vector2D(path.get_position(c.sidewalk, 0).x - c.args.clearance_pedestrian,
                               path.get_position(c.sidewalk, 0).y - c.args.clearance_pedestrian),
                carla.Vector2D(path.get_position(c.sidewalk, 0).x + c.args.clearance_pedestrian,
                               path.get_position(c.sidewalk, 0).y + c.args.clearance_pedestrian))):
            trans = carla.Transform()
            trans.location.x = path.get_position(c.sidewalk, 0).x
            trans.location.y = path.get_position(c.sidewalk, 0).y
            trans.location.z = 0.5
            trans.rotation.yaw = path.get_yaw(c.sidewalk, 0)
            actor = c.world.try_spawn_actor(c.rng.choice(c.pedestrian_blueprints), trans)
            c.world.wait_for_tick(1.0) # Without this, the actor list gets messed up in CARLA, leading to random actors spawning.
            if actor:
                actor.set_collision_enabled(c.args.collision)
                c.world.wait_for_tick(1.0)  # For actor to update pos and bounds, and for collision to apply.
                aabb_map.insert(get_aabb(actor))
                pedestrian_agents.append(Agent(
                    actor.id, 'People', path, 1.0 + c.rng.uniform(-0.5, 0.5)))

def do_gamma(c, car_agents, bike_agents, pedestrian_agents):
    agents = car_agents + bike_agents + pedestrian_agents
    agents_lookup = {}
    for agent in agents:
        agents_lookup[agent.actor_id] = agent

    next_agents = []
    next_agent_gamma_ids = []
    agents_to_destroy = []
    if len(agents) > 0:
        gamma = carla.RVOSimulator()
        
        gamma_id = 0
        for actor in c.world.get_actors():
            if actor.id not in agents_lookup: # For external agents not tracked.
                if isinstance(actor, carla.Vehicle):
                    if actor.attributes['number_of_wheels'] == 2:
                        type_tag = 'Bicycle'
                    else:
                        type_tag = 'Car'
                    bounding_box_corners = get_vehicle_bounding_box_corners(actor)
                elif isinstance(actor, carla.Walker):
                    type_tag = 'People'
                    bounding_box_corners = get_pedestrian_bounding_box_corners(actor)
                else:
                    continue

                gamma.add_agent(carla.AgentParams.get_default(type_tag), gamma_id)
                gamma.set_agent_position(gamma_id, get_position(actor))
                gamma.set_agent_velocity(gamma_id, get_velocity(actor))
                gamma.set_agent_heading(gamma_id, get_forward_direction(actor))
                gamma.set_agent_bounding_box_corners(gamma_id, bounding_box_corners)
                gamma.set_agent_pref_velocity(gamma_id, get_velocity(actor))
                gamma_id += 1
            else: # For tracked agents.
                agent = agents_lookup[actor.id]

                # Declare variables.
                is_valid = True
                pref_vel = None
                path_forward = None
                bounding_box_corners = None
                lane_constraints = None

                # Update path, check validity, process variables.
                if agent.type_tag == 'Car' or agent.type_tag == 'Bicycle':
                    position = get_position(actor)
                    # Lane change if possible.
                    if c.rng.uniform(0.0, 1.0) <= c.args.lane_change_probability:
                        new_path_candidates = c.sumo_network.get_next_route_paths(
                                c.sumo_network.get_nearest_route_point(position),
                                agent.path.min_points - 1, agent.path.interval)
                        if len(new_path_candidates) > 0:
                            new_path = SumoNetworkAgentPath(c.rng.choice(new_path_candidates)[0:agent.path.min_points], 
                                    agent.path.min_points, agent.path.interval)
                            agent.path = new_path
                    # Cut, resize, check.
                    if not agent.path.resize(c.sumo_network):
                        is_valid = False
                    else:
                        agent.path.cut(c.sumo_network, position)
                        if not agent.path.resize(c.sumo_network):
                            is_valid = False
                    # Calculate variables.
                    if is_valid:
                        target_position = agent.path.get_position(c.sumo_network, 5)  ## to check
                        velocity = (target_position - position).make_unit_vector()
                        pref_vel = agent.preferred_speed * velocity
                        path_forward = (agent.path.get_position(c.sumo_network, 1) - 
                                agent.path.get_position(c.sumo_network, 0)).make_unit_vector()
                        bounding_box_corners = get_vehicle_bounding_box_corners(actor)
                        side_constraints = get_lane_constraints(c.sidewalk, position, path_forward)
                elif agent.type_tag == 'People':
                    position = get_position(actor)
                    # Cut, resize, check.
                    if not agent.path.resize(c.sidewalk, c.args.cross_probability):
                        is_valid = False
                    else:
                        agent.path.cut(c.sidewalk, position)
                        if not agent.path.resize(c.sidewalk, c.args.cross_probability):
                            is_valid = False
                    # Calculate pref_vel.
                    if is_valid:
                        target_position = agent.path.get_position(c.sidewalk, 0)
                        velocity = (target_position - position).make_unit_vector()
                        pref_vel = agent.preferred_speed * velocity
                        path_forward = carla.Vector2D(0, 0) # Irrelevant for pedestrian.
                        bounding_box_corners = get_pedestrian_bounding_box_corners(actor)
                
                # Add info to GAMMA.
                if pref_vel:
                    gamma.add_agent(carla.AgentParams.get_default(agent.type_tag), gamma_id)
                    gamma.set_agent_position(gamma_id, get_position(actor))
                    gamma.set_agent_velocity(gamma_id, get_velocity(actor))
                    gamma.set_agent_heading(gamma_id, get_forward_direction(actor))
                    gamma.set_agent_bounding_box_corners(gamma_id, bounding_box_corners)
                    gamma.set_agent_pref_velocity(gamma_id, pref_vel)
                    gamma.set_agent_path_forward(gamma_id, path_forward)
                    if lane_constraints is not None:
                        # Flip LR -> RL since GAMMA uses right-handed instead.
                        gamma.set_agent_lane_constraints(gamma_id, lane_constraints[1], lane_constraints[0])  
                    next_agents.append(agent)
                    next_agent_gamma_ids.append(gamma_id)
                    gamma_id += 1
                else:
                    agents_to_destroy.append(agent)

        gamma.do_step()

        for (agent, gamma_id) in zip(next_agents, next_agent_gamma_ids):
            agent.control_velocity = gamma.get_agent_velocity(gamma_id)

    car_agents[:] = [a for a in next_agents if a.type_tag == 'Car']
    bike_agents[:] = [a for a in next_agents if a.type_tag == 'Bicycle']
    pedestrian_agents[:] = [a for a in next_agents if a.type_tag == 'People']

    c.client.apply_batch_sync([carla.command.DestroyActor(a.actor_id) for a in agents_to_destroy])
    c.world.wait_for_tick(1.0)

    c.crowd_service.acquire_control_velocities()
    c.crowd_service.control_velocities = [
            (agent.actor_id, agent.type_tag, agent.control_velocity, agent.preferred_speed, agent.steer_angle_range)
            for agent in next_agents]
    c.crowd_service.release_control_velocities()
   
    local_intentions = []
    for agent in next_agents:
        if agent.type_tag == 'People':
            local_intentions.append((agent.actor_id, agent.type_tag, agent.path.route_points[0], agent.path.route_orientations[0]))
        else:
            local_intentions.append((agent.actor_id, agent.type_tag, agent.path.route_points[0]))

    c.crowd_service.acquire_local_intentions()
    c.crowd_service.local_intentions = local_intentions
    c.crowd_service.release_local_intentions()

def do_control(c, pid_integrals, pid_last_errors, pid_last_update_time):
    start = time.time()

    c.crowd_service.acquire_control_velocities()
    control_velocities = c.crowd_service.control_velocities
    c.crowd_service.release_control_velocities()

    commands = []
    cur_time = time.time()
    if pid_last_update_time is None:
        dt = 0.0
    else:
        dt = cur_time - pid_last_update_time

    for (actor_id, type_tag, control_velocity, preferred_speed, steer_angle_range) in control_velocities:
        actor = c.world.get_actor(actor_id)
        if actor is None:
            if actor_id in pid_integrals:
                del pid_integrals[actor_id]
            if actor_id in pid_last_errors:
                del pid_last_errors[actor_id]
            continue

        cur_vel = get_velocity(actor)

        angle_diff = get_signed_angle_diff(control_velocity, cur_vel)
        if angle_diff > 30 or angle_diff < -30:
            target_speed = 0.5 * (control_velocity + cur_vel)

        if type_tag == 'Car' or type_tag == 'Bicycle':
            speed = get_velocity(actor).length()
            target_speed = control_velocity.length()
            control = actor.get_control()

            # Calculate error.
            speed_error = target_speed - speed

            # Add to integral.
            pid_integrals[actor_id] += speed_error * dt

            kp = CAR_SPEED_KP if type_tag == 'Car' else BIKE_SPEED_KP
            ki = CAR_SPEED_KI if type_tag == 'Car' else BIKE_SPEED_KI
            kd = CAR_SPEED_KD if type_tag == 'Car' else BIKE_SPEED_KD

            # Calculate output.
            speed_control = kp * speed_error + ki * pid_integrals[actor_id]
            if pid_last_update_time is not None and actor_id in pid_last_errors:
                speed_control += kd * (speed_error - pid_last_errors[actor_id]) / dt
            
            # Update history.
            pid_last_errors[actor_id] = speed_error

            # Set control.
            if speed_control >= 0:
                control.throttle = speed_control
                control.brake = 0.0
                control.hand_brake = False
            else:
                control.throttle = 0.0
                control.brake = -speed_control
                control.hand_brake = False
            control.steer = np.clip(
                    np.clip(
                        kp * get_signed_angle_diff(control_velocity, get_forward_direction(actor)), 
                        -45.0, 45.0) / steer_angle_range,
                    -1.0, 1.0)
            control.manual_gear_shift = True # DO NOT REMOVE: Reduces transmission lag.
            control.gear = 1 # DO NOT REMOVE: Reduces transmission lag.
            
            # Append to commands.
            commands.append(carla.command.ApplyVehicleControl(actor_id, control))

        elif type_tag == 'People':
            velocity = np.clip(control_velocity.length(), 0.0, preferred_speed) * control_velocity.make_unit_vector()
            control = carla.WalkerControl(carla.Vector3D(velocity.x, velocity.y), 1.0, False)
            commands.append(carla.command.ApplyWalkerControl(actor_id, control))

    c.client.apply_batch_sync(commands)

    return cur_time # New pid_last_update_time.

def control_loop(args):
    # Wait for crowd service.
    time.sleep(2)
    c = Context(args)
    print('Control loop running.')
            
    pid_integrals = defaultdict(float)
    pid_last_errors = defaultdict(float)
    pid_last_update_time = None 

    while True:
        start = time.time()
        pid_last_update_time = do_control(c, pid_integrals, pid_last_errors, pid_last_update_time)
        time.sleep(max(0, 0.05 - (time.time() - start)))
        #print('Control rate: {} Hz'.format(1 / max(time.time() - start, 0.001)))

def gamma_loop(args):
    # Wait for crowd service.
    time.sleep(2)
    c = Context(args)
    print('GAMMA loop running.')
    
    car_agents = []
    bike_agents = []
    pedestrian_agents = []

    while True:
        start = time.time()
        do_destroy(c, car_agents, bike_agents, pedestrian_agents)
        do_spawn(c, car_agents, bike_agents, pedestrian_agents)
        do_gamma(c, car_agents, bike_agents, pedestrian_agents)
        time.sleep(max(0, 0.02 - (time.time() - start)))
        #print('GAMMA rate: {} Hz'.format(1 / max(time.time() - start, 0.001)))

def main():
    argparser = argparse.ArgumentParser(
        description=__doc__)
    argparser.add_argument(
        '--host',
        default='127.0.0.1',
        help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument(
        '-p', '--port',
        default=2000,
        type=int,
        help='TCP port to listen to (default: 2000)')
    argparser.add_argument(
        '-d', '--dataset',
        default='meskel_square',
        help='Name of dataset (default: meskel_square)')
    argparser.add_argument(
        '-s', '--seed',
        default='-1',
        help='Value of random seed (default: -1)',
        type=int)
    argparser.add_argument(
        '--collision',
        help='Enables collision for controlled agents',
        action='store_true')
    argparser.add_argument(
        '--num-car',
        default='20',
        help='Number of cars to spawn (default: 20)',
        type=int)
    argparser.add_argument(
        '--num-bike',
        default='20',
        help='Number of bikes to spawn (default: 20)',
        type=int)
    argparser.add_argument(
        '--num-pedestrian',
        default='20',
        help='Number of pedestrians to spawn (default: 20)',
        type=int)
    argparser.add_argument(
        '--clearance-car',
        default='7.0',
        help='Minimum clearance (m) when spawning a car (default: 7.0)',
        type=float)
    argparser.add_argument(
        '--clearance-bike',
        default='7.0',
        help='Minimum clearance (m) when spawning a bike (default: 7.0)',
        type=float)
    argparser.add_argument(
        '--clearance-pedestrian',
        default='1.0',
        help='Minimum clearance (m) when spawning a pedestrian (default: 1.0)',
        type=float)
    argparser.add_argument(
        '--lane-change-probability',
        default='0.0',
        help='Probability of lane change for cars and bikes (default: 0.0)',
        type=float)
    argparser.add_argument(
        '--cross-probability',
        default='0.1',
        help='Probability of crossing road for pedestrians (default: 0.1)',
        type=float)
    argparser.add_argument(
        '--stuck-speed',
        default='0.2',
        help='Maximum speed (m/s) for an agent to be considered stuck (default: 0.2)',
        type=float)
    argparser.add_argument(
        '--stuck-duration',
        default='5.0',
        help='Minimum duration (s) for an agent to be considered stuck (default: 5)',
        type=float)
    args = argparser.parse_args()

    control_process = Process(target=control_loop, args=(args,))
    control_process.daemon = True
    control_process.start()
    
    gamma_process = Process(target=gamma_loop, args=(args,))
    gamma_process.daemon = True
    gamma_process.start()
    
    Pyro4.Daemon.serveSimple(
            {
                CrowdService: "crowdservice.warehouse"
            },
            port=8100,
            ns=False)

if __name__ == '__main__':
    main()
