"""Optional live check: a tiny embedding/chat request, no index creation or writes.

Run explicitly with --live. Credentials and provider response bodies are never printed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if sys.argv[1:] != ['--live']:
        print('Use --live to perform small billable provider checks with local .env keys.')
        return 2
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from core.embeddings import embed_texts, embed_query
    from core.generation import generate_answer

    passed = True
    for name, check in [
        ('Pinecone passage embedding', lambda: len(embed_texts(['Water has formula H2O.'])[0]) == 1024),
        ('Pinecone query embedding', lambda: len(embed_query('What is the formula of water?')) == 1024),
        ('Groq streaming answer', lambda: bool(''.join(generate_answer(
            'What formula is reported? Answer briefly.',
            [{'doc_name': 'check.cif', 'locator': 'data_water, tag _chemical_formula_sum',
              'text': '_chemical_formula_sum = "H2 O"'}], stream=True)).strip())),
    ]:
        try:
            ok = check()
            print(name + (': PASS' if ok else ': FAIL'))
            passed = passed and ok
        except Exception as error:
            # Response bodies may include provider internals; report safe fields.
            status = getattr(error, 'status_code', None) or getattr(error, 'status', None)
            print(f'{name}: FAIL ({type(error).__name__}, status={status})')
            passed = False
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
