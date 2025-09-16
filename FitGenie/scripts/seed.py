import requests
API="https://turbo-space-dollop-977gxxjj565qf95r9-5000.app.github.dev/"
H={"X-User-Id":"U123"}
requests.post(f"{API}/auth/login", json={"userId":"U123","name":"Demo User"})
print("Seeded demo user U123")
