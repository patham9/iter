import urllib.request
import json

DESCRIPTION = "Get weather for a city using wttr.in. Pass city name as string."

def run(city):
    """
    city: str - city name (e.g. 'Vienna', 'New York')
    returns: str - weather summary
    """
    try:
        safe_city = city.replace(' ', '+')
        url = f"http://wttr.in/{safe_city}?format=j1"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        current = data.get('current_condition', [{}])[0]
        temp = current.get('temp_C', '?')
        feels = current.get('FeelsLikeC', '?')
        desc_list = current.get('weatherDesc', [{}])
        desc = desc_list[0].get('value', '?') if desc_list else '?'
        humidity = current.get('humidity', '?')
        wind = current.get('windspeedKmph', '?')
        
        return f"{city}: {desc}, {temp}°C (feels {feels}°C), humidity {humidity}%, wind {wind}km/h"
    except Exception as e:
        return f"ERROR: {e}"
