import csv
import json
import sys


def parse_json(json_data):
    try:
        data = json.loads(json_data)
        file_names = [item["file"] for item in data["ranked_list"]]
        
        return file_names
    except json.JSONDecodeError as e:
        # print("Failed to parse JSON:", e)
        return []
    except KeyError as e:
        # print("Missing expected key:", e)
        return []


def process_bug_results(csv_path):
    bug_results = {}
    with open(csv_path, newline='', encoding='utf-8', errors='ignore') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            bug_id = row['bug_id']
            try:
                suspicious_files = parse_json(row['suspicious_files'])
                fixed_files = row['fixed_files'].split(',')
                
                bug_results[bug_id] = {
                    'suspicious_files': suspicious_files,
                    'fixed_files': fixed_files
                }
            except Exception as e:
                    print(e)
                
    return bug_results

def check_localization_at_k(fixed_files, suspicious_files, k):
    """Return True if any fixed file is in the top-k suspicious files."""
    top_files = suspicious_files[:k]
    for fixed_file in fixed_files:
        if fixed_file in top_files:
            return True
    return False

def process_bugs_localized_at_k(project, csv_path):
    bug_results = process_bug_results(csv_path)
    acc1_ids, acc5_ids, acc10_ids = [], [], []
    
    for bug_id, result in bug_results.items():
        suspicious_files = result['suspicious_files']
        fixed_files = result['fixed_files']

        if check_localization_at_k(fixed_files, suspicious_files, 1):
            acc1_ids.append(bug_id)
        if check_localization_at_k(fixed_files, suspicious_files, 5):
            acc5_ids.append(bug_id)
        if check_localization_at_k(fixed_files, suspicious_files, 10):
            acc10_ids.append(bug_id)

    max_len = max(len(acc1_ids), len(acc5_ids), len(acc10_ids))
    rows = []
    for i in range(max_len):
        rows.append([
            acc1_ids[i] if i < len(acc1_ids) else "",
            acc5_ids[i] if i < len(acc5_ids) else "",
            acc10_ids[i] if i < len(acc10_ids) else ""
        ])

    out_file = f"localized_bugs_{project}.csv"
    with open(out_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["accuracy@1", "accuracy@5", "accuracy@10"])
        writer.writerows(rows)

    print(f"Wrote bug IDs to {out_file}")


if __name__ == "__main__":
    project = sys.argv[1]
    input_filename = project+'_final_ranked_output.csv'
    process_bugs_localized_at_k(project, input_filename)