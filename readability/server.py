from flask import Flask, request
from readability import get_article

app = Flask('readability')


@app.route('/')
def readerize():
    return get_article(request.args.get('url'))


if __name__ == '__main__':
    app.run(port=8040, debug=True)

