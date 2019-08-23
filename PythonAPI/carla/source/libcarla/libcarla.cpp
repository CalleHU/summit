// Copyright (c) 2017 Computer Vision Center (CVC) at the Universitat Autonoma
// de Barcelona (UAB).
//
// This work is licensed under the terms of the MIT license.
// For a copy, see <https://opensource.org/licenses/MIT>.

#include <carla/Memory.h>
#include <carla/PythonUtil.h>
#include <carla/Time.h>

#include <ostream>
#include <type_traits>
#include <vector>

template <typename OptionalT>
static boost::python::object OptionalToPythonObject(OptionalT &optional) {
  return optional.has_value() ? boost::python::object(*optional) : boost::python::object();
}

// Convenient for requests without arguments.
#define CALL_WITHOUT_GIL(cls, fn) +[](cls &self) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return self.fn(); \
    }

// Convenient for requests with 1 argument.
#define CALL_WITHOUT_GIL_1(cls, fn, T1_) +[](cls &self, T1_ t1) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return self.fn(std::forward<T1_>(t1)); \
    }

// Convenient for requests with 2 arguments.
#define CALL_WITHOUT_GIL_2(cls, fn, T1_, T2_) +[](cls &self, T1_ t1, T2_ t2) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return self.fn(std::forward<T1_>(t1), std::forward<T2_>(t2)); \
    }

// Convenient for requests with 3 arguments.
#define CALL_WITHOUT_GIL_3(cls, fn, T1_, T2_, T3_) +[](cls &self, T1_ t1, T2_ t2, T3_ t3) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return self.fn(std::forward<T1_>(t1), std::forward<T2_>(t2), std::forward<T3_>(t3)); \
    }

// Convenient for requests with 4 arguments.
#define CALL_WITHOUT_GIL_4(cls, fn, T1_, T2_, T3_, T4_) +[](cls &self, T1_ t1, T2_ t2, T3_ t3, T4_ t4) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return self.fn(std::forward<T1_>(t1), std::forward<T2_>(t2), std::forward<T3_>(t3), std::forward<T4_>(t4)); \
    }

// Convenient for const requests without arguments.
#define CONST_CALL_WITHOUT_GIL(cls, fn) CALL_WITHOUT_GIL(const cls, fn)
#define CONST_CALL_WITHOUT_GIL_1(cls, fn, T1_) CALL_WITHOUT_GIL_1(const cls, fn, T1_)
#define CONST_CALL_WITHOUT_GIL_2(cls, fn, T1_, T2_) CALL_WITHOUT_GIL_2(const cls, fn, T1_, T2_)
#define CONST_CALL_WITHOUT_GIL_3(cls, fn, T1_, T2_, T3_) CALL_WITHOUT_GIL_3(const cls, fn, T1_, T2_, T3_)
#define CONST_CALL_WITHOUT_GIL_4(cls, fn, T1_, T2_, T3_, T4_) CALL_WITHOUT_GIL_4(const cls, fn, T1_, T2_, T3_, T4_)

// Convenient for static requests without arguments.
#define STATIC_CALL_WITHOUT_GIL(cls, fn) +[]() { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return cls::fn(); \
    }

// Convenient for static requests with 1 argument.
#define STATIC_CALL_WITHOUT_GIL_1(cls, fn, T1_) +[](T1_ t1) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      return cls::fn(std::forward<T1_>(t1)); \
    }

// Convenient for const requests that need to make a copy of the returned value.
#define CALL_RETURNING_COPY(cls, fn) +[](const cls &self) \
        -> std::decay_t<std::result_of_t<decltype(&cls::fn)(cls*)>> { \
      return self.fn(); \
    }

// Convenient for const requests that need to make a copy of the returned value.
#define CALL_RETURNING_COPY_1(cls, fn, T1_) +[](const cls &self, T1_ t1) \
        -> std::decay_t<std::result_of_t<decltype(&cls::fn)(cls*, T1_)>> { \
      return self.fn(std::forward<T1_>(t1)); \
    }

// Convenient for const requests that needs to convert the return value to a
// Python list.
#define CALL_RETURNING_LIST(cls, fn) +[](const cls &self) { \
      boost::python::list result; \
      for (auto &&item : self.fn()) { \
        result.append(item); \
      } \
      return result; \
    }

// Convenient for const requests that needs to convert the return value to a
// Python list.
#define CALL_RETURNING_LIST_1(cls, fn, T1_) +[](const cls &self, T1_ t1) { \
      boost::python::list result; \
      for (auto &&item : self.fn(std::forward<T1_>(t1))) { \
        result.append(item); \
      } \
      return result; \
    }

#define CALL_RETURNING_LIST_2(cls, fn, T1_, T2_) +[](const cls &self, T1_ t1, T2_ t2) { \
      boost::python::list result; \
      for (auto &&item : self.fn(std::forward<T1_>(t1), std::forward<T2_>(t2))) { \
        result.append(item); \
      } \
      return result; \
    }

#define CALL_RETURNING_OPTIONAL(cls, fn) +[](const cls &self) { \
      auto optional = self.fn(); \
      return OptionalToPythonObject(optional); \
    }

#define CALL_RETURNING_OPTIONAL_1(cls, fn, T1_) +[](const cls &self, T1_ t1) { \
      auto optional = self.fn(std::forward<T1_>(t1)); \
      return OptionalToPythonObject(optional); \
    }

#define CALL_RETURNING_OPTIONAL_WITHOUT_GIL(cls, fn) +[](const cls &self) { \
      carla::PythonUtil::ReleaseGIL unlock; \
      auto optional = self.fn(); \
      return optional.has_value() ? boost::python::object(*optional) : boost::python::object(); \
    }

template <typename T>
static void PrintListItem_(std::ostream &out, const T &item) {
  out << item;
}

template <typename T>
static void PrintListItem_(std::ostream &out, const carla::SharedPtr<T> &item) {
  if (item == nullptr) {
    out << "nullptr";
  } else {
    out << *item;
  }
}

template <typename Iterable>
static std::ostream &PrintList(std::ostream &out, const Iterable &list) {
  out << '[';
  if (!list.empty()) {
    auto it = list.begin();
    PrintListItem_(out, *it);
    for (++it; it != list.end(); ++it) {
      out << ", ";
      PrintListItem_(out, *it);
    }
  }
  out << ']';
  return out;
}

namespace std {

  template <typename T>
  std::ostream &operator<<(std::ostream &out, const std::vector<T> &vector_of_stuff) {
    return PrintList(out, vector_of_stuff);
  }

} // namespace std

static carla::time_duration TimeDurationFromSeconds(double seconds) {
  size_t ms = static_cast<size_t>(1e3 * seconds);
  return carla::time_duration::milliseconds(ms);
}

static auto MakeCallback(boost::python::object callback) {
  namespace py = boost::python;
  // Make sure the callback is actually callable.
  if (!PyCallable_Check(callback.ptr())) {
    PyErr_SetString(PyExc_TypeError, "callback argument must be callable!");
    py::throw_error_already_set();
  }

  // We need to delete the callback while holding the GIL.
  using Deleter = carla::PythonUtil::AcquireGILDeleter;
  auto callback_ptr = carla::SharedPtr<py::object>{new py::object(callback), Deleter()};

  // Make a lambda callback.
  return [callback=std::move(callback_ptr)](auto message) {
    carla::PythonUtil::AcquireGIL lock;
    try {
      py::call<void>(callback->ptr(), py::object(message));
    } catch (const py::error_already_set &) {
      PyErr_Print();
    }
  };
}

#include "Geom.cpp"
#include "Occupancy.cpp"
#include "Gamma.cpp"
#include "Landmark.cpp"
#include "Actor.cpp"
#include "Blueprint.cpp"
#include "Client.cpp"
#include "Control.cpp"
#include "Exception.cpp"
#include "Map.cpp"
#include "Sensor.cpp"
#include "SensorData.cpp"
#include "Sidewalk.cpp"
#include "Snapshot.cpp"
#include "SumoNetwork.cpp"
#include "Weather.cpp"
#include "World.cpp"
#include "Commands.cpp"

BOOST_PYTHON_MODULE(libcarla) {
  using namespace boost::python;
  PyEval_InitThreads();
  numpy::initialize();
  scope().attr("__path__") = "libcarla";
  export_geom();
  export_sumo_network();
  export_occupancy();
  export_landmark();
  export_control();
  export_gamma();
  export_sidewalk();
  export_blueprint();
  export_actor();
  export_sensor();
  export_sensor_data();
  export_snapshot();
  export_weather();
  export_world();
  export_map();
  export_client();
  export_exception();
  export_commands();
}
