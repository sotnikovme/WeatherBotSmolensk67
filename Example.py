import os
import requests
from datetime import datetime, timedelta



API_KEY = "48b221bd88c2691ad84bb4e29ecf81ff"


def get_weather_params(city: str):
    url = "https://api.openweathermap.org/data/2.5/forecast"

    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    first_datetime = datetime.strptime(
        data["list"][0]["dt_txt"],
        "%Y-%m-%d %H:%M:%S"
    )
    target_date = (first_datetime.date() + timedelta(days=1)).isoformat()
    target_times = {
        "morning": "09:00:00",
        "midday": "12:00:00",
        "day": "15:00:00",
        "evening": "21:00:00",
    }

    result = {}

    for item in data["list"]:
        date_part, time_part = item["dt_txt"].split(" ")

        if date_part != target_date:
            continue

        for part_of_day, target_time in target_times.items():
            if time_part == target_time:
                result[part_of_day] = {
                "time": item["dt_txt"],
                "temperature": item["main"]["temp"],
                "humidity": item["main"]["humidity"],
                "weather": item["weather"][0]["main"],
                "description": item["weather"][0]["description"],
                "clouds": item["clouds"]["all"],
                "wind_speed": item["wind"]["speed"],
                "rain": item.get("rain", {}).get("3h", 0),
            }

    return result


weather = get_weather_params("Moscow")
print(weather)
