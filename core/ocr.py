"""Local, bounded Poppler + Tesseract OCR. No image leaves the server."""
import csv
import io
from pathlib import Path
import shutil
import subprocess
import tempfile

def available():
    return bool(shutil.which('pdftoppm') and shutil.which('tesseract'))

def pdf_page(path,number):
    if not available():
        raise ValueError('This PDF needs OCR. Use the Docker app with Poppler and Tesseract installed.')
    with tempfile.TemporaryDirectory() as folder:
        prefix = str(Path(folder)/'page')
        commands = [
            ['pdftoppm','-f',str(number),'-l',str(number),'-singlefile','-scale-to','2200','-png',str(path),prefix],
            ['tesseract',prefix+'.png','stdout','-l','eng','--psm','3','tsv']]
        try:
            subprocess.run(commands[0],check=True,capture_output=True,timeout=30)
            result = subprocess.run(commands[1],check=True,capture_output=True,timeout=30)
        except (subprocess.SubprocessError,OSError):
            raise ValueError(f'OCR could not finish page {number}. Check the original scan.') from None
        if len(result.stdout)>4*1024*1024:
            raise ValueError('OCR output exceeded the safety limit')
        words,confidence,last_line = [],[],None
        for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8',errors='replace')),delimiter='\t'):
            text = row.get('text','').strip()
            if not text:
                continue
            line = tuple(row.get(key) for key in ('page_num','block_num','par_num','line_num'))
            if words and line!=last_line:
                words.append('\n')
            words.append(text)
            last_line = line
            try:
                value = float(row.get('conf','-1'))
                if 0<=value<=100:
                    confidence.append(value)
            except ValueError:
                pass
        return ' '.join(words),sum(confidence)/len(confidence) if confidence else 0.
