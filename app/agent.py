# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext, load_memory, preload_memory
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

# Load environment variables from local .env if available
def load_env_vars():
    env_paths = [
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), ".env"),
        ".env",
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k not in os.environ:
                            os.environ[k] = v.strip("\"'")
            break

load_env_vars()

# Hardcoded project ID & Cloud Storage bucket name as required
GCP_PROJECT_ID = "qwiklabs-gcp-02-3bdea787ca30"
GCS_BUCKET_NAME = "fitness-coach-media-qwiklabs-gcp-02-3bdea787ca30"

# Load Agent Engine resource name from deployment_metadata.json for sandbox code execution
def get_agent_engine_resource_name() -> str:
    meta_path = os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
                return meta.get("remote_agent_runtime_id", "")
        except Exception:
            pass
    return "projects/257236958011/locations/us-east1/reasoningEngines/7697344455501676544"

agent_engine_resource_name = get_agent_engine_resource_name()
agent_engine_id = agent_engine_resource_name.split("/")[-1]

code_executor = AgentEngineSandboxCodeExecutor(agent_engine_resource_name=agent_engine_resource_name)

# Memory Bank Service for Agent Platform deployment
memory_service = VertexAiMemoryBankService(
    project=GCP_PROJECT_ID,
    location="us-east1",
    agent_engine_id=agent_engine_id,
)


def get_firestore_client() -> firestore.Client:
    """Returns a Firestore client initialized with hardcoded GCP project ID."""
    key_path = "/config/sa-key.json"
    if os.path.exists(key_path) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
    return firestore.Client(project=GCP_PROJECT_ID)


def list_workouts(category: str = "") -> str:
    """Lists available workout routines from the Firestore database.

    Args:
        category: Optional category filter (e.g. 'Strength', 'Cardio', 'Recovery'). If empty, lists all routines.

    Returns:
        A list of matching workout routines stored in Firestore.
    """
    db = get_firestore_client()
    query = db.collection("workouts")
    docs = list(query.stream())
    
    results = []
    for d in docs:
        data = d.to_dict()
        if not category or category.lower() in data.get("category", "").lower():
            results.append(data)
            
    if not results:
        return f"No workouts found matching category: '{category}'" if category else "No workouts found in database."
        
    return str(results)


def save_workout_routine(
    name: str,
    category: str,
    duration_minutes: int,
    target_zone: str,
    exercises: list[str],
    notes: str = ""
) -> str:
    """Saves a new workout routine to the Firestore database.

    Args:
        name: Name of the workout routine (e.g. 'Leg Day & Core').
        category: Category of workout (e.g. 'Strength', 'Cardio', 'Recovery').
        duration_minutes: Estimated duration in minutes.
        target_zone: Target heart rate or intensity zone (e.g. 'Zone 2 (Endurance)', 'Zone 3 (Aerobic)').
        exercises: List of exercise names included in the routine.
        notes: Optional extra guidance or set/rep instructions.

    Returns:
        Confirmation string indicating the workout routine was successfully logged.
    """
    db = get_firestore_client()
    doc_id = f"workout_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
    data = {
        "id": doc_id,
        "name": name,
        "category": category,
        "duration_minutes": duration_minutes,
        "target_zone": target_zone,
        "exercises": exercises,
        "notes": notes,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.collection("workouts").document(doc_id).set(data)
    return f"Successfully saved workout routine '{name}' with ID '{doc_id}' to Firestore."


def calculate_training_zones(age: int, resting_hr: int = 60, max_hr: int = 0) -> str:
    """Calculates personalized target heart rate training zones (Zone 1 to Zone 5).

    Args:
        age: User's age in years.
        resting_hr: User's resting heart rate in BPM (default: 60).
        max_hr: Optional explicit maximum heart rate in BPM (default 0 calculates as 220 - age).

    Returns:
        A formatted summary of heart rate zones with BPM ranges using the Karvonen formula.
    """
    effective_max_hr = max_hr if max_hr > 0 else (220 - age)
    hrr = effective_max_hr - resting_hr  # Heart Rate Reserve

    zones = {
        "max_heart_rate": effective_max_hr,
        "resting_heart_rate": resting_hr,
        "zones": {
            "Zone 1 (Active Recovery)": f"{int(resting_hr + hrr * 0.50)} - {int(resting_hr + hrr * 0.60)} BPM (50-60%)",
            "Zone 2 (Aerobic Endurance)": f"{int(resting_hr + hrr * 0.60)} - {int(resting_hr + hrr * 0.70)} BPM (60-70%)",
            "Zone 3 (Tempo / Aerobic)": f"{int(resting_hr + hrr * 0.70)} - {int(resting_hr + hrr * 0.80)} BPM (70-80%)",
            "Zone 4 (Lactate Threshold)": f"{int(resting_hr + hrr * 0.80)} - {int(resting_hr + hrr * 0.90)} BPM (80-90%)",
            "Zone 5 (Anaerobic / Max)": f"{int(resting_hr + hrr * 0.90)} - {effective_max_hr} BPM (90-100%)",
        }
    }
    return str(zones)


def fetch_live_weather(location: str) -> str:
    """Fetches real-time weather data from Open-Meteo API for outdoor workout planning.

    Args:
        location: City or location name (e.g. 'New York', 'San Francisco', 'London').

    Returns:
        Real-time temperature, wind speed, and weather conditions for outdoor fitness planning.
    """
    api_key = os.environ.get("OPENMETEO_API_KEY", "")  # Open-Meteo is free; reads env key if provided
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(location)}&count=1"
        req = urllib.request.Request(geo_url, headers={"User-Agent": "FitnessCoachAgent/1.0"})
        with urllib.request.urlopen(req) as resp:
            geo_data = json.loads(resp.read().decode())

        if not geo_data.get("results"):
            return f"Location '{location}' not found."

        loc = geo_data["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]
        city_name = loc.get("name", location)
        country = loc.get("country", "")

        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        req_w = urllib.request.Request(weather_url, headers={"User-Agent": "FitnessCoachAgent/1.0"})
        with urllib.request.urlopen(req_w) as resp_w:
            weather_data = json.loads(resp_w.read().decode())

        cw = weather_data.get("current_weather", {})
        temp_c = cw.get("temperature")
        temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else "N/A"
        wind_speed = cw.get("windspeed")

        return (
            f"Live outdoor weather for {city_name}, {country}: "
            f"Temperature: {temp_c}°C ({temp_f}°F), Wind Speed: {wind_speed} km/h."
        )
    except Exception as e:
        return f"Error fetching live weather data for '{location}': {str(e)}"


def geocode_address(address: str) -> str:
    """Converts an address or location into latitude and longitude coordinates using Google Geocoding API.

    Args:
        address: Street address or location name (e.g. 'Central Park, New York, NY').

    Returns:
        A dictionary string containing formatted address, latitude, and longitude.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "FitnessCoachAgent/1.0"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") != "OK" or not data.get("results"):
            return f"Geocoding failed for '{address}'. Status: {data.get('status')}"

        res = data["results"][0]
        formatted_addr = res.get("formatted_address")
        location = res.get("geometry", {}).get("location", {})

        return str({
            "address": formatted_addr,
            "latitude": location.get("lat"),
            "longitude": location.get("lng")
        })
    except Exception as e:
        return f"Error geocoding address '{address}': {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "gym",
    radius_meters: float = 3000.0
) -> str:
    """Finds nearby places of interest (e.g. gym, park, fitness_center) near coordinates using Google Places API (New).

    Args:
        latitude: Latitude coordinate.
        longitude: Longitude coordinate.
        place_type: Type of place to search for (e.g. 'gym', 'park', 'fitness_center', 'sports_complex').
        radius_meters: Search radius in meters (default 3000.0).

    Returns:
        A list string of nearby places with name, formatted address, and location coordinates.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    try:
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.types"
        }
        body = {
            "includedTypes": [place_type],
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude
                    },
                    "radius": float(radius_meters)
                }
            },
            "maxResultCount": 5
        }

        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        places = data.get("places", [])
        if not places:
            return f"No nearby places of type '{place_type}' found within {radius_meters}m."

        results = []
        for p in places:
            display_name = p.get("displayName", {}).get("text", "N/A")
            addr = p.get("formattedAddress", "N/A")
            loc = p.get("location", {})
            results.append({
                "name": display_name,
                "address": addr,
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude")
                }
            })

        return str(results)
    except Exception as e:
        return f"Error finding nearby places: {str(e)}"


async def generate_workout_visual(
    prompt: str,
    tool_context: ToolContext = None
) -> str:
    """Generates a motivational workout visual or fitness image using gemini-3.1-flash-lite-image model in global region and uploads it to Cloud Storage.

    Args:
        prompt: Description of the workout scene or visual to generate (e.g. 'A motivational athlete running outdoors at sunrise').
        tool_context: ADK ToolContext automatically injected by the framework.

    Returns:
        The public HTTPS GCS URL of the generated image.
    """
    try:
        # Initialize Google GenAI client in global region using vertexai
        client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=f"A professional high-quality fitness visual showing: {prompt}",
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"]
            )
        )

        image_bytes = None
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    break

        if not image_bytes:
            return "Error: Image generation model did not return image bytes."

        filename = f"visual_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}.jpg"

        # 1. Save as artifact if tool_context is provided
        if tool_context is not None:
            part_artifact = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            await tool_context.save_artifact(filename=filename, artifact=part_artifact)

        # 2. Upload image bytes directly in memory to Cloud Storage bucket
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return f"Successfully generated fitness visual! Public URL: {public_url}"

    except Exception as e:
        return f"Error generating workout visual: {str(e)}"


async def generate_workout_video(
    prompt: str,
    tool_context: ToolContext = None
) -> str:
    """Generates a short workout or exercise demonstration video using gemini-omni-flash-preview model in global region and uploads it to Cloud Storage.

    Args:
        prompt: Description of the workout video to generate (e.g. 'A short video demonstrating proper squat form').
        tool_context: ADK ToolContext automatically injected by the framework.

    Returns:
        The public HTTPS GCS URL of the generated video.
    """
    try:
        # Initialize Google GenAI client in global region using vertexai
        client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-omni-flash-preview",
            contents=f"A short video demonstrating: {prompt}",
            config=types.GenerateContentConfig(
                response_modalities=["VIDEO"]
            )
        )

        video_bytes = None
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    video_bytes = part.inline_data.data
                    break

        if not video_bytes:
            return "Error: Video generation model did not return video bytes."

        filename = f"video_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}.mp4"

        # 1. Save as artifact if tool_context is provided
        if tool_context is not None:
            part_artifact = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
            await tool_context.save_artifact(filename=filename, artifact=part_artifact)

        # 2. Upload video bytes directly in memory to Cloud Storage bucket
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type="video/mp4")

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return f"Successfully generated workout video! Public URL: {public_url}"

    except Exception as e:
        return f"Error generating workout video: {str(e)}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are an expert Fitness & Workout Coach agent. "
        "You help users manage, retrieve, and log workout routines and heart-rate training plans. "
        "Pay strict attention to remembering and honoring all user allergies, dietary restrictions, and health preferences. "
        "Whenever a user shares any food allergies (e.g. peanuts, tree nuts, shellfish, dairy, gluten) or medical/dietary preferences, ensure it is stored in long-term memory. "
        "Use `load_memory` or memory tools to retrieve remembered user facts and allergies before recommending workouts, post-workout meals, or nutrition advice. "
        "Use `list_workouts` to retrieve stored workout routines and `save_workout_routine` to record new ones. "
        "Use `calculate_training_zones` to compute personalized heart rate training zones. "
        "Use `fetch_live_weather` to retrieve real-time weather metrics when planning outdoor workouts. "
        "Use `geocode_address` to convert location names/addresses to lat/lng coordinates. "
        "Use `find_nearby_places` to discover gyms, parks, and fitness facilities near given coordinates. "
        "Use `generate_workout_visual` to create motivational fitness imagery and workout visuals. "
        "Use `generate_workout_video` to create video demonstrations of exercises or routines."
    ),
    workflow_description="Analyze the user request, run appropriate tools, and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=a2ui_instruction,
    after_model_callback=a2ui_callback,
    tools=[
        load_memory,
        preload_memory,
        list_workouts,
        save_workout_routine,
        calculate_training_zones,
        fetch_live_weather,
        geocode_address,
        find_nearby_places,
        generate_workout_visual,
        generate_workout_video,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)




