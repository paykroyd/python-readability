import sys
from flask import Flask, request
from readability import Document
import requests

app = Flask('readability')


@app.route('/')
def readerize():
    enc = sys.__stdout__.encoding or 'utf-8'
    doc = Document(url=request.args.get('url'))
    html = doc.get_clean_article().encode(enc, 'replace')
    return html

if __name__ == '__main__':
    app.run(port=8040, debug=True)

