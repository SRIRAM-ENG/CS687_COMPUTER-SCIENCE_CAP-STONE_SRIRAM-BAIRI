import time, random, requests, os

API = os.getenv("API","https://turbo-space-dollop-977gxxjj565qf95r9-5000.app.github.dev/")
HEADERS = {"X-User-Id":"U123"}

def push(metric, val):
    requests.post(f"{API}/me/metrics", json={"metricType": metric, "value": val}, headers=HEADERS, timeout=5)

if __name__ == "__main__":
    print("Simulating sensor data → Ctrl+C to stop")
    while True:
        push("HR", random.randint(70, 95))
        push("Steps", random.randint(100, 800))
        if random.random() < .3:
            push("SleepScore", random.randint(60, 85))
        time.sleep(5)
