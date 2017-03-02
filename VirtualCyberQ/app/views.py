from app import app
from flask import render_template
from flask import request
from flask import Response

from status import Status

@app.route('/config.xml')
def config():
    return response_of('config.xml')

@app.route('/status.xml')
def status():
    return response_of('status.xml')

@app.route('/all.xml')
def all():
    return response_of('all.xml')

@app.route('/', methods=['GET'])
def index():
    return "%s This is a virtual implementation of the CyberQ BBQ Control Device" % Status.instance().time_remaining()

@app.route('/', methods=['POST'])
def update():
    status = Status.instance()
    updates = request.get_data().split("&")
    for u in updates:
        key, value = u.split("=")
        print "updating {0} to {1}".format(key, value)
        status.update(key, value)

    return ""

def response_of(template):
    content = render_template(template, status=Status.instance())
    return Response(content, mimetype='text/xml')
