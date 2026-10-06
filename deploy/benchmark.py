"""Offline by default; --compare explicitly permits embedding quota use."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from core.benchmark import run

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--compare',action='store_true')
    parser.add_argument('--fixture')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    report = run(args.compare,args.fixture)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['metrics'],indent=2))
