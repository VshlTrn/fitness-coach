"""Seed script for populating Firestore with initial workout routines."""

from google.cloud import firestore

# Hardcoded project ID as required to prevent project number resolution issues on Agent Platform
GCP_PROJECT_ID = "qwiklabs-gcp-02-3bdea787ca30"

INITIAL_WORKOUTS = [
    {
        "id": "workout_001",
        "name": "Full-Body Strength & Conditioning",
        "category": "Strength",
        "duration_minutes": 45,
        "target_zone": "Zone 3 (Aerobic)",
        "exercises": ["Barbell Squats", "Push-ups", "Dumbbell Rows", "Plank Hold"],
        "notes": "Perform 3 sets of 10-12 reps per exercise.",
    },
    {
        "id": "workout_002",
        "name": "High-Intensity Interval Training (HIIT)",
        "category": "Cardio",
        "duration_minutes": 30,
        "target_zone": "Zone 4 (Threshold)",
        "exercises": ["Burpees", "Mountain Climbers", "Jump Squats", "Sprint Intervals"],
        "notes": "40 seconds work, 20 seconds rest for 4 rounds.",
    },
    {
        "id": "workout_003",
        "name": "Active Recovery & Mobility Flow",
        "category": "Recovery",
        "duration_minutes": 25,
        "target_zone": "Zone 1 (Recovery)",
        "exercises": ["Cat-Cow Stretch", "Downward Dog", "Hip Openers", "Foam Rolling"],
        "notes": "Focus on deep breathing and joint mobility.",
    },
    {
        "id": "workout_004",
        "name": "Endurance Running & Core",
        "category": "Cardio",
        "duration_minutes": 60,
        "target_zone": "Zone 2 (Endurance)",
        "exercises": ["5km Steady Run", "Bicycle Crunches", "Leg Raises", "Russian Twists"],
        "notes": "Maintain conversational pace during the run.",
    }
]

def seed_database():
    print(f"Connecting to Firestore for project '{GCP_PROJECT_ID}'...")
    db = firestore.Client(project=GCP_PROJECT_ID)
    collection_ref = db.collection("workouts")

    for item in INITIAL_WORKOUTS:
        doc_ref = collection_ref.document(item["id"])
        doc_ref.set(item)
        print(f"Seeded workout: {item['name']} ({item['id']})")

    print("Firestore seeding completed successfully!")

if __name__ == "__main__":
    seed_database()
