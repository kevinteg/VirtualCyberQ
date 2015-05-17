from app import app
from flask import render_template
from flask import request

from status import Status

@app.route('/config.xml')
def config():
    return render_template('config.xml', status=Status.instance())

@app.route('/status.xml')
def status():
    return render_template('status.xml', status=Status.instance())

@app.route('/all.xml')
def all():
    return render_template('all.xml', status=Status.instance())

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
