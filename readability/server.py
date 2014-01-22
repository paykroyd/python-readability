import sys
from flask import Flask, request
from readability import Document
import requests

app = Flask('readability')


@app.route('/')
def readerize():
    resp = requests.get(request.args.get('url'))
    resp.raise_for_status()
    enc = sys.__stdout__.encoding or 'utf-8'
    html = Document(resp.text, debug=True, url=request.args.get('url')).summary().encode(enc, 'replace')


    return html

if __name__ == '__main__':
    app.run(port=8040)

