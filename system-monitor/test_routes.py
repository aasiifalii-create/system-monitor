"""Quick test of metrics_api routes"""
from metrics_api import app

print("URL Map:")
for rule in app.url_map.iter_rules():
    print(f"  {rule.rule} -> {rule.endpoint}")
