"""One-row live RAGAS check, no Pinecone index reads or writes."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if sys.argv[1:] != ['--live']:
        print('Pass --live for one small provider-backed RAGAS evaluation.')
        return 2
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from phases.phase3_hard.ragas_eval import run_ragas_eval, METRICS
    rows = [{'question': 'What is the chemical formula of water?',
             'ground_truth': 'The chemical formula of water is H2O.',
             'answer': 'The chemical formula of water is H2O.',
             'contexts': ['Water has the chemical formula H2O.']}]
    with tempfile.TemporaryDirectory() as folder:
        os.environ['DOCUMIND_DATA_DIR'] = folder
        os.environ['RAGAS_REPORT_DIR'] = folder
        try:
            summary = run_ragas_eval(rows, 'live_check')
            print('Evaluator model:', summary['evaluator_model'])
            for metric in METRICS:
                print(f"{metric}: {summary[metric] if summary[metric] is not None else 'FAILED'}")
            print('CSV report:', 'PASS' if Path(summary['csv_path']).is_file() else 'FAIL')
            return 1 if summary['failed_cells'] else 0
        except Exception as error:
            print(f'Evaluation failed: {type(error).__name__}; status={getattr(error, "status_code", None)}')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
