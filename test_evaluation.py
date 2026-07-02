#!/usr/bin/env python
"""Test job matching evaluation"""
from ai_answerer import QuestionAnswerer

print("Testing job evaluation with AI...\n")

answerer = QuestionAnswerer()

test_jd = """
Senior DevOps Engineer at TechCorp
Location: Bangalore, India
Experience: 3-6 years
Skills: Kubernetes, Docker, CI/CD, AWS, Terraform, Python
Salary: ₹60-80 LPA

Responsibilities:
- Design and maintain Kubernetes clusters
- Implement CI/CD pipelines using Jenkins
- Manage AWS infrastructure with Terraform
- Mentor junior DevOps engineers
"""

print("Evaluating job match...")
score, reason = answerer.match_job_score(
    job_title="Senior DevOps Engineer",
    company="TechCorp",
    location="Bangalore",
    salary="60-80 LPA",
    experience="3-6 years",
    skills="Kubernetes, Docker, CI/CD, AWS",
    full_description=test_jd
)

print(f"Match Score: {score}%")
print(f"Reason: {reason}")

if score > 0:
    print("\n✅ Job evaluation is working!")
else:
    print("\n❌ Job evaluation failed")
