import sys
from flask import Flask, request
from readability import get_article
import requests

app = Flask('readability')


@app.route('/')
def readerize():
    html = get_article(request.args.get('url'))
    return html

if __name__ == '__main__':
    app.run(port=8040, debug=True)

