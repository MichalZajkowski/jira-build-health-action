import argparse
import xml.etree.ElementTree as ET
import json
import os
import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict

class BuildHealthAgent:
    """
    Analizuje wyniki testów w formacie JUnit XML, oblicza wskaźniki kondycji
    i przesyła podsumowanie do Jiry.
    """
    FAILURE_PENALTY = 10

    def __init__(self):
        self.score = 100
        self.total_duration = 0.0
        self.current_failures = []
        self.test_history = defaultdict(list)
        self.last_status = {}

    def process_builds(self, xml_files):
        """
        Przetwarza listę plików XML z wynikami testów.

        Args:
            xml_files (list): Lista ścieżek do plików XML.
        """
        print(f"Processing {len(xml_files)} XML file(s)...")
        for file_path in xml_files:
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()

                # Sumaryczny czas wykonania z <testsuite>
                duration = float(root.get('time', 0))
                self.total_duration += duration

                for testcase in root.findall('testcase'):
                    self._process_testcase(testcase)

            except ET.ParseError as e:
                print(f"Error parsing XML file {file_path}: {e}")
            except FileNotFoundError:
                print(f"Error: XML file not found at {file_path}")

        print("Finished processing build files.")

    def _process_testcase(self, testcase):
        """Przetwarza pojedynczy element <testcase>."""
        name = testcase.get('name')
        status = 'PASS'
        error_message = ''

        failure = testcase.find('failure')
        if failure is not None:
            status = 'FAIL'
            self.score -= self.FAILURE_PENALTY
            error_message = failure.get('message', 'No message')
            self.current_failures.append({"test": name, "error": error_message})

        error = testcase.find('error')
        if error is not None:
            status = 'FAIL'
            if status != 'FAIL': # Unikaj podwójnej kary
                 self.score -= self.FAILURE_PENALTY
                 self.current_failures.append({"test": name, "error": error_message})
            error_message = error.get('message', 'No message')


        if testcase.find('skipped') is not None:
            status = 'SKIP'

        self.test_history[name].append(status)
        self.last_status[name] = status

    def _identify_flaky_tests(self):
        """
        Identyfikuje testy, które w przeszłości kończyły się niepowodzeniem,
        ale w ostatnim przebiegu zakończyły się sukcesem.
        """
        flaky_tests = []
        for name, history in self.test_history.items():
            is_flaky = 'FAIL' in history and self.last_status.get(name) == 'PASS'
            if is_flaky:
                flaky_tests.append(name)
        return flaky_tests

    def upload_to_jira(self, issue_key, domain, email, token):
        """
        Generuje raport w formacie JSON i wysyła go do Jiry jako Entity Property.
        """
        flaky_tests = self._identify_flaky_tests()
        
        # Ogranicz wynik do minimum 0
        final_score = max(0, self.score)

        summary_status = "FAIL" if self.current_failures else "PASS"

        payload = {
            "summary": {
                "score": final_score,
                "status": summary_status,
                "totalDuration": round(self.total_duration, 4)
            },
            "flakyTests": flaky_tests,
            "currentFailures": self.current_failures
        }

        print("Generated JSON Payload:")
        print(json.dumps(payload, indent=2))

        url = f"https://{domain}/rest/api/3/issue/{issue_key}/properties/build_health_data"
        auth = HTTPBasicAuth(email, token)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        print(f"Uploading data to Jira issue {issue_key}...")
        try:
            response = requests.put(
                url,
                data=json.dumps(payload),
                headers=headers,
                auth=auth,
                timeout=30
            )
            response.raise_for_status()
            print("Successfully uploaded build health data to Jira.")
            print(f"Status Code: {response.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"Error uploading to Jira: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response Status: {e.response.status_code}")
                print(f"Response Body: {e.response.text}")
            # Zakończ z błędem, aby zatrzymać GitHub Action
            exit(1)

def main():
    parser = argparse.ArgumentParser(description="Analyze JUnit XML files and upload results to Jira.")
    parser.add_argument('xml_files', nargs='+', help='Glob pattern or list of XML files')
    parser.add_argument('--issue', required=True, help='Jira Issue Key (e.g., DEV-1)')
    parser.add_argument('--domain', required=True, help='Jira Domain (e.g., your-domain.atlassian.net)')
    parser.add_argument('--email', required=True, help='Your Jira account email')
    parser.add_argument('--token', required=True, help='Your Jira API Token')
    
    args = parser.parse_args()

    agent = BuildHealthAgent()
    agent.process_builds(args.xml_files)
    agent.upload_to_jira(args.issue, args.domain, args.email, args.token)

if __name__ == "__main__":
    main()