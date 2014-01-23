from flask import Flask, request
from readability import get_article, NotArticle

app = Flask('readability')


@app.route('/')
def readerize():
    if not request.args.get('url'):
        raise ValueError()

    try:
        return '<html><head><link rel="stylesheet" type="text/css" href="/static/style.css"></head><body>' + \
               get_article(request.args.get('url')) + "</body></html>"
    except NotArticle:
        return 'not article'


if __name__ == '__main__':
    app.run(port=8040, debug=True)

