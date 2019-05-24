#include "CrowdController.h"
#include "EngineUtils.h"
#include "Engine/StaticMeshActor.h"
#include "Regex.h"
#include "Polygon.h"

ACrowdController::ACrowdController(void) {
  PrimaryActorTick.bCanEverTick = true; 
  PrimaryActorTick.TickGroup = TG_PrePhysics;
  bAllowTickBeforeBeginPlay = false;
}

ACrowdController::ACrowdController(const FObjectInitializer &ObjectInitializer)
  : Super(ObjectInitializer) {
  PrimaryActorTick.bCanEverTick = true; 
  PrimaryActorTick.TickGroup = TG_PrePhysics;
  bAllowTickBeforeBeginPlay = false;
}

void ACrowdController::Tick(float DeltaSeconds) {
  FVector2D Point = RandRoadPoint();
  FTransform Transform(FVector(Point.X, Point.Y, 10));
  
  const FActorDefinition& ActorDefinition = RandWalkerActorDefinition();
  FActorDescription ActorDescription;
  ActorDescription.UId = ActorDefinition.UId;
  ActorDescription.Id = ActorDefinition.Id;
  ActorDescription.Class = ActorDefinition.Class;

  Episode->SpawnActor(Transform, ActorDescription);
}

FVector2D ACrowdController::RandRoadPoint() const {
  float V = FMath::FRandRange(0, TotalRoadArea);
  
  for (const FPolygon& Polygon : RoadPolygons){
    V -= Polygon.GetArea();
    if (V <= 0) return Polygon.RandPoint();
  }

  return RoadPolygons.Last().RandPoint();
}

const FActorDefinition& ACrowdController::RandWalkerActorDefinition() const {
  const TArray<FActorDefinition>& ActorDefinitions = Episode->GetActorDefinitions();
  TArray<const FActorDefinition*> WalkerActorDefinitions;
  
  for (const FActorDefinition& ActorDefinition : ActorDefinitions) {
    if (FRegexMatcher(FRegexPattern(TEXT("(|.*,)walker(|,.*)")), ActorDefinition.Tags).FindNext()) {

      WalkerActorDefinitions.Add(&ActorDefinition);
    }
  }

  return *WalkerActorDefinitions[FMath::RandRange(0, WalkerActorDefinitions.Num() - 1)];
}

void ACrowdController::Initialize() {
  TotalRoadArea = 0;
  for (TActorIterator<AStaticMeshActor> ActorItr(GetWorld()); ActorItr; ++ActorItr) {
    if (ActorItr->GetFolderPath().ToString() == TEXT("Roads")) {
      const FPositionVertexBuffer& VertexBuffer = ActorItr->GetStaticMeshComponent()->GetStaticMesh()->RenderData->LODResources[0].VertexBuffers.PositionVertexBuffer;
      TArray<FVector2D> Vertices;
      int Count = VertexBuffer.GetNumVertices();
      for (int Index = 0; Index < Count; Index++) {
        const FVector Vertex3 = GetActorLocation() + GetTransform().TransformVector(VertexBuffer.VertexPosition(Index));
        Vertices.Emplace(Vertex3.X, Vertex3.Y);
      }
      TotalRoadArea += RoadPolygons[RoadPolygons.Emplace(Vertices)].GetArea();
    }
  }

  for (int I = 0; I < 10; I++) {
    FVector2D Point = RandRoadPoint();
    FTransform Transform(FVector(Point.X, Point.Y, 10));
  }
}
