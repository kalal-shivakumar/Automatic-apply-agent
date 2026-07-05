import json

with open("debug_linkedin_apply_flow_results.json", encoding="utf-8") as f:
    d = json.load(f)

print("ok:", d["ok"])
print("message:", d["message"])
print("applied_count:", d["applied_count"])
print("inspected_count:", d["inspected_count"])
print()
print("Steps completed:")
for k, v in d["steps"].items():
    mark = "PASS" if v else "FAIL"
    print(f"  [{mark}] {k}")

statuses = {}
for j in d.get("jobs", []):
    s = j.get("status", "?")
    statuses[s] = statuses.get(s, 0) + 1
print()
print("Status breakdown:", statuses)
print()

for j in d.get("jobs", []):
    if j.get("ai_answers"):
        print("JOB:", j["title"][:55], "@", j["company"][:30], "| score=", j.get("match_score", "?"))
        for a in j["ai_answers"]:
            print("  [" + a["kind"] + "] " + a["question"][:55] + " => " + str(a["ai_answer"])[:55])
        print()
