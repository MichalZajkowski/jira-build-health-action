import argparse
import xml.etree.ElementTree as ET
import json
import sys
import os
import requests
import glob  # <--- NOWOŚĆ: Biblioteka do obsługi gwiazdek
from requests.auth import HTTPBasicAuth

# Stałe
PROPERTY_KEY = "build_health_data"
STARTING_SCORE = 100
PENALTY_CURRENT_FAILURE = 20
PENALTY_FLAKY_TEST = 10
THRESHOLD_STABLE = 80
THRESHOLD_UNSTABLE = 50


class TestResult:
    def __init__(self, name, status, message="", duration=0.0):
        self.name = name
        self.status = status
        self.message = message
        self.duration = duration


class BuildHealthAgent:
    def __init__(self):
        self.history = {}
        self.latest_results = {}
        self.total_duration = 0.0

    def parse_xml_file(self, file_path):
        results = []
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except Exception as e:
            print(f"Warning: Nie można sparsować {file_path}: {e}", file=sys.stderr)
            return []

        suites = root.findall('testsuite') if root.tag == 'testsuites' else [root]
        for suite in suites:
            for case in suite.findall('testcase'):
                full_name = f"{case.get('classname', 'unknown')}.{case.get('name', 'unknown')}"
                duration = float(case.get('time', 0.0))
                status = "PASS"
                message = ""

                if case.find('failure') is not None:
                    status = "FAIL"
                    fail_node = case.find('failure')
                    message = fail_node.get('message', '') or fail_node.text or "Unknown failure"
                elif case.find('error') is not None:
                    status = "FAIL"
                    err_node = case.find('error')
                    message = err_node.get('message', '') or err_node.text or "Unknown error"
                elif case.find('skipped') is not None:
                    status = "SKIP"

                results.append(TestResult(full_name, status, message, duration))
        return results

    def process_builds(self, file_patterns):
        # --- POPRAWKA: Rozwijanie gwiazdek (Globbing) ---
        expanded_files = []
        for pattern in file_patterns:
            # Glob expanduje np. "build_*.xml" na ["build_1.xml", "build_2.xml"]
            found = glob.glob(pattern)
            if not found:
                # Jeśli plik podany wprost (bez gwiazdki) nie istnieje, to ostrzeżenie
                print(f"Warning: File pattern returned no files: {pattern}")
            expanded_files.extend(found)

        # Sortowanie, żeby kolejność historii była zachowana (1, 2, 3)
        expanded_files.sort()

        if not expanded_files:
            print("Error: No valid XML files found to process.")
            # Nie wychodzimy exit(1), żeby spróbować wysłać chociaż status 0 do Jiry
            return

        print(f"Processing {len(expanded_files)} XML file(s): {expanded_files}")

        for idx, file_path in enumerate(expanded_files):
            results = self.parse_xml_file(file_path)
            is_latest = (idx == len(expanded_files) - 1)

            if is_latest:
                self.total_duration = sum(r.duration for r in results)

            for result in results:
                if result.name not in self.history: self.history[result.name] = []
                self.history[result.name].append(result.status)
                if is_latest: self.latest_results[result.name] = result

    def generate_payload(self):
        current_failures = [r for r in self.latest_results.values() if r.status == "FAIL"]

        flaky_tests = []
        for name, statuses in self.history.items():
            if len(statuses) >= 2 and statuses[-1] == "PASS" and "FAIL" in statuses[:-1]:
                flaky_tests.append(name)

        score = max(0, STARTING_SCORE - (len(current_failures) * PENALTY_CURRENT_FAILURE) - (
                    len(flaky_tests) * PENALTY_FLAKY_TEST))

        status = "Stable"
        if score < THRESHOLD_UNSTABLE:
            status = "Critical"
        elif score < THRESHOLD_STABLE:
            status = "Unstable"

        formatted_failures = []
        for fail in current_failures:
            clean_msg = (fail.message or "").strip().replace("\n", " ")
            formatted_failures.append({
                "test": fail.name,
                "error": (clean_msg[:97] + "...") if len(clean_msg) > 100 else clean_msg
            })

        return {
            "summary": {"score": score, "status": status, "totalDuration": round(self.total_duration, 2)},
            "flakyTests": flaky_tests,
            "currentFailures": formatted_failures
        }

    def upload_to_jira(self, issue_key, domain, email, token):
        # --- ZABEZPIECZENIE URL ---
        # Usuwamy https:// jeśli użytkownik wpisał to w Secrecie
        clean_domain = domain.replace("https://", "").replace("/", "")

        url = f"https://{clean_domain}/rest/api/3/issue/{issue_key}/properties/{PROPERTY_KEY}"

        print(f"Uploading data to Jira issue {issue_key}...")

        try:
            response = requests.put(
                url,
                json=self.generate_payload(),
                auth=HTTPBasicAuth(email, token),
                headers={"Accept": "application/json", "Content-Type": "application/json"}
            )

            if response.status_code in [200, 201, 204]:
                print(f"✅ SUCCESS! Data saved to {issue_key}.")
            else:
                print(f"Error uploading to Jira: {response.status_code}")
                print(f"Response Body: {response.text}")
                sys.exit(1)  # Fail the action if Jira upload fails
        except Exception as e:
            print(f"Connection Error: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('xml_files', nargs='+', help='XML files or glob patterns')
    parser.add_argument('--issue', required=True)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--token', required=True)

    args = parser.parse_args()

    agent = BuildHealthAgent()
    agent.process_builds(args.xml_files)
    agent.upload_to_jira(args.issue, args.domain, args.email, args.token)


if __name__ == "__main__":
    main()