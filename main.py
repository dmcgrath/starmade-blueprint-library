"""`main` is the top level module for your Flask application."""

from google.appengine.ext import blobstore, ndb
from flask import Flask, render_template, request, make_response, redirect, url_for
from struct import Struct
from werkzeug import parse_options_header
import block_mass
import json
import math
import logging
import zipfile

app = Flask(__name__)

SCHEMA_VERSION_CURRENT = 9
CONTEXT_VERSION_CURRENT = 2

block_mass.init()

class Blueprint(ndb.Model):
    blob_key = ndb.StringProperty(indexed=False)
    schema_version = ndb.IntegerProperty(indexed=True, default=SCHEMA_VERSION_CURRENT)
    context = ndb.JsonProperty(indexed=False)
    elements = ndb.JsonProperty(indexed=False)
    element_count = ndb.IntegerProperty(indexed=True)
    title = ndb.StringProperty(indexed=True)
    context_version = ndb.IntegerProperty(indexed=True, default=CONTEXT_VERSION_CURRENT)

# http://stackoverflow.com/a/3155023/153407
millnames=['','K','M','B','T']
def millify(n):
    n = float(n)
    millidx=max(0,min(len(millnames)-1,
                      int(math.floor(math.log10(abs(n))/3))))
    return '%.0f %s'%(n/10**(3*millidx),millnames[millidx])

@app.route("/upload")
def upload():
    uploadUri = blobstore.create_upload_url('/submit', gs_bucket_name='blueprints')
    return render_template('upload.html', uploadUri=uploadUri)

@app.route("/submit", methods=['POST'])
def submit():
    if request.method == 'POST':
        f = request.files['file']
        blueprint_title = None
        header = f.headers['Content-Type']
        parsed_header = parse_options_header(header)
        blob_key = parsed_header[1]['blob-key']

        blue_key = process_blueprint(blob_key, blueprint_title)

        return render_template('finished_upload.html', blue_key=blue_key.urlsafe())

def process_blueprint(blob_key, blueprint_title, blue_key=None):
    blob_info = blobstore.get(blob_key)
    blob = blob_info.open()

    with zipfile.ZipFile(file=blob, mode="r") as zip_file:
        for filename in (name for name in zip_file.namelist() if name.endswith('/header.smbph') and name.count('/') <= 1):
            blueprint_title = filename[:filename.find("/")].replace("_", " ")
            header_blob = zip_file.open(filename)
            return process_header(blob_key, header_blob, blueprint_title, blue_key)

def calc_power_output(block_count, ship_dimensions):
    block_power = block_count * 25.0
    max_dimensions = block_count + 2.0
    if max_dimensions > ship_dimensions:
        remainder_dimensions = (block_count % (ship_dimensions-2.0)) + 2.0
        max_mod = (block_count - remainder_dimensions - 2.0) / (ship_dimensions-2.0)
        group_power = pow(ship_dimensions/3.0,1.7) * max_mod + pow(remainder_dimensions/3.0,1.7)
        size_power = (2.0/(1.0+pow(1.000696,-0.333*group_power))-1.0)*1000000.0               
    else:
        size_power = (2/(1+pow(1.000696,-0.333*pow(max_dimensions/3.0,1.7)))-1.0)*1000000.0
    return block_power + size_power

def calc_power_capacity(block_count):
    return 1000.0 * pow(block_count, 1.05)

def calc_thrust(block_count):
    return pow(block_count * 5.5, 0.87) * 0.75

def calc_speed_coefficient(block_count, total_mass):
    return min(block_count / total_mass, 2.5) + 0.5

def calc_thrust_power(block_count):
    return block_count / 0.03

def calc_shield_capacity(block_count):
    return pow(block_count, 0.9791797578) * 110.0 + 220.0

def calc_shield_recharge(block_count):
    return block_count * 5.5

def calc_shield_power(block_count, active=False):
    if active:
        return block_count * 55.0 
    else:
        return block_count * 5.5

def calc_jump_power(block_count, total_mass):
    ideal = math.ceil(total_mass * 0.5)
    a = 50.0 - 100.0 * block_count * total_mass
    return (-0.24 * total_mass)*a*a + 4600.0*a + 230000.0 + 1200.0 * ideal

def calc_jump_time(jump_power, block_count):
    return jump_power / (10000.0 + 50.0 * block_count)

def process_header(blob_key, blob, blueprint_title, blue_key=None):
    version_struct = Struct('>i')
    ver = version_struct.unpack(blob.read(version_struct.size))[0]
    if ver > 65535:
        endian = '<'
        ver =  ((ver<<24)&0xFF000000)|((ver<<8)&0xFF0000)|((ver>>8)&0xFF00)|((ver>>24)&0xFF)
    else:
        endian = '>'
    header_struct = Struct(endian+'I3f3fi') # entityEnum<unsigned int>, minPoint<3xfloat>, maxPoint<3xfloat>, numElements<int>
    block_struct = Struct(endian+'hi') # BlockID<short>, blockCount<int>

    result = []
    result = header_struct.unpack(blob.read(header_struct.size))

    context = {
       "title": blueprint_title,
       "version": ver,
       "entity": result[0],
       "length": int(result[6]-result[3])-2, # -2 since core-only blueprint gives 2, -1 respectively.
       "width": int(result[4]-result[1])-2,
       "height": int(result[5]-result[2])-2,
       "power_recharge": {"base":1},
       "power_capacity": {"base":50000},
       "power_usage": {},
       "thrust": "None",
       "shields": {"capacity": 220, "recharge": 0},
       "systems" : {"medical":0, "factory":0},
       "speed_coefficient" : 0
    }

    ship_dimensions = context['length'] + context['width'] + context['height']
    element_count = result[7]
    element_list = []
    total_block_count = 0
    total_mass = 0
    complex_systems = {"salvage":0, "astrotech":0, "power_drain":0,
                       "power_supply":0, "shield_drain":0, "shield_supply":0}

    for element in xrange(0, element_count):
        new_element = block_struct.unpack(blob.read(block_struct.size))
        element_list.append([new_element])
        block_id = new_element[0]
        block_count = new_element[1]
        total_block_count += block_count
        total_mass += block_count * block_mass.NON_STANDARD_MASS.get(block_id, 0.1)
        if block_id == 2: # Power Block
            power_output = calc_power_output(block_count, ship_dimensions)
            context['power_recharge']['ideal_generator'] = round(power_output,1)
        elif block_id == 331: # Power Capacitor
            power_capacity = calc_power_capacity(block_count)
            context['power_capacity']['ideal_capacitor'] = round(power_capacity,0)
        elif block_id == 8: # Thruster Block
            context['thrust'] = round(calc_thrust(block_count),1)
            context['power_usage']['thruster'] = round(-calc_thrust_power(block_count),0)
        elif block_id == 3: # Shield Capacitor Block
            context['shields']['capacity'] = round(calc_shield_capacity(block_count),0)
        elif block_id == 478: # Shield Recharger Block
            shield_power_standby = calc_shield_power(block_count)
            shield_power_active = calc_shield_power(block_count, True)
            shield_recharge = calc_shield_recharge(block_count)
            context['shields']['recharge'] = round(shield_recharge,0)
            context['power_recharge']['shields'] = -round(shield_power_standby,0)
            context['power_usage']['shield_recharge'] = -round(shield_power_active,0)
        elif block_id == 15: # Radar Jamming
            context['systems']['radar_jamming'] = block_count
        elif block_id == 22: # Cloaking
            context['systems']['cloaking'] = block_count
        elif block_id == 291: # Faction
            context['systems']['faction'] = block_count
        elif block_id == 347: # Shop
            context['systems']['shop'] = block_count
        elif block_id == 94: # Plex Undeathinator
            context['systems']['plexundeathinator'] = block_count
        elif block_id >= 211 and block_id <= 215: # Factory equipment
            context['systems']['factory'] += block_count
        elif block_id == 121: # AI
            context['systems']['bobby_ai'] = block_count
        elif block_id == 445 or block_id == 446: # Medical Equipment
            context['systems']['medical'] += block_count
        elif block_id == 47: # Cameras
            context['systems']['camera'] = block_count
        elif block_id == 4: # Salvage Computer
            if complex_systems['salvage'] == 0:
                complex_systems['salvage'] = 1
            else:
                context['systems']['salvage'] = complex_systems['salvage']
        elif block_id == 24: # Salvage Modules
            if complex_systems['salvage'] == 0:
                complex_systems['salvage'] = block_count
            else:
                context['systems']['salvage'] = block_count
        elif block_id == 39: # Astrotech Computer
            if complex_systems['astrotech'] == 0:
                complex_systems['astrotech'] = 1
            else:
                context['systems']['astrotech'] = complex_systems['astrotech']
        elif block_id == 30: # Astrotech Modules
            if complex_systems['astrotech'] == 0:
                complex_systems['astrotech'] = block_count
            else:
                context['systems']['astrotech'] = block_count
        elif block_id == 332: # Power Drain Computer
            if complex_systems['power_drain'] == 0:
                complex_systems['power_drain'] = 1
            else:
                context['systems']['power_drain'] = complex_systems['power_drain']
        elif block_id == 333: # Power Drain Modules
            if complex_systems['power_drain'] == 0:
                complex_systems['power_drain'] = block_count
            else:
                context['systems']['power_drain'] = block_count
        elif block_id == 334: # Power Supply Computer
            if complex_systems['power_supply'] == 0:
                complex_systems['power_supply'] = 1
            else:
                context['systems']['power_supply'] = complex_systems['power_supply']
        elif block_id == 335: # Power Drain Modules
            if complex_systems['power_supply'] == 0:
                complex_systems['power_supply'] = block_count
            else:
                context['systems']['power_supply'] = block_count
        elif block_id == 46: # Shield Drain Computer
            if complex_systems['shield_drain'] == 0:
                complex_systems['shield_drain'] = 1
            else:
                context['systems']['shield_drain'] = complex_systems['shield_drain']
        elif block_id == 40: # Shield Drain Modules
            if complex_systems['shield_drain'] == 0:
                complex_systems['shield_drain'] = block_count
            else:
                context['systems']['shield_drain'] = block_count
        elif block_id == 54: # Shield Supply Computer
            if complex_systems['shield_supply'] == 0:
                complex_systems['shield_supply'] = 1
            else:
                context['systems']['shield_supply'] = complex_systems['shield_supply']
        elif block_id == 48: # Shield Supply Modules
            if complex_systems['shield_supply'] == 0:
                complex_systems['shield_supply'] = block_count
            else:
                context['systems']['shield_supply'] = block_count

    if 'radar_jamming' in context['systems']:
        context['power_usage']['radar_jamming'] = -total_mass * 50
    if 'cloaking' in context['systems']:
        context['power_usage']['cloaking'] = -total_mass * 14.5

    context['element_list'] = element_list
    context['mass'] = round(total_mass,1)

    context['systems'] = {key:value for key,value in context['systems'].iteritems() if value > 0}

    max_thrust_ratio = calc_thrust(total_mass) / context['mass']
    thrust_gauge = 0
    if context['thrust'] != 'None':
        thrust_ratio = context['thrust'] / context['mass']
        if thrust_ratio <= 1:
            thrust_gauge = thrust_ratio * 0.5
        else:
            thrust_gauge = (math.log(thrust_ratio)/math.log(max_thrust_ratio))*0.5+0.5

        context['speed_coefficient'] = round(calc_speed_coefficient(context['thrust'], total_mass),1)

    shields = context['shields']
    if shields['capacity']<1:
       shield_capacity_gauge = 0
    else:
       max_shields = calc_shield_capacity(total_block_count)
       scgs = math.sin((shields['capacity']/max_shields)*math.pi/2)
       scgl = math.log(shields['capacity'])/math.log(max_shields)
       shield_capacity_gauge = (scgs+scgl)/2.0
    if shields['recharge']<1:
       shield_recharge_gauge = 0
    else:
        max_shields_recharge = calc_shield_recharge(total_block_count)
        srgs = math.sin((shields['recharge']/max_shields_recharge)*math.pi/2.0)
        srgl = math.log(shields['recharge'])/math.log(max_shields_recharge)
        shield_recharge_gauge = (srgs+srgl)/2.0

    context['thrust_gauge'] = round(thrust_gauge * 100.0,1)
    context['shield_capacity_gauge'] = round(shield_capacity_gauge * 100.0,1)
    context['shield_recharge_gauge'] = round(shield_recharge_gauge * 100.0,1)
    context['power_recharge_sum'] = sum(context['power_recharge'].itervalues())
    context['power_capacity_sum'] = sum(context['power_capacity'].itervalues())

    if context['power_recharge_sum'] > 0:
        context['idle_time_charge'] = round(float(context['power_capacity_sum'])/context['power_recharge_sum'],1)
    else:
        context['idle_time_charge'] = "N/A"

    if blue_key == None:
        blueprint = Blueprint()
    else:
        blueprint = ndb.Key(urlsafe=blue_key).get()
        blueprint.schema_version = SCHEMA_VERSION_CURRENT
        blueprint.context_version = CONTEXT_VERSION_CURRENT

    blueprint.blob_key = blob_key
    blueprint.context = json.dumps(context)
    blueprint.elements = json.dumps(element_list)
    blueprint.title = blueprint_title
    blue_key = blueprint.put()

    return blue_key

@app.route("/blueprint/<blob_key>")
def download_blueprint(blob_key):
    blob_info = blobstore.get(blob_key)
    response = make_response(blob_info.open().read())
    response.headers['Content-Type'] = blob_info.content_type
    return response

@app.route("/view/<blue_key>")
def view(blue_key):
    roman = {-1:"N",0:"N",1:"I",2:"II",3:"III",4:"IV",5:"V",6:"VI",7:"VII",8:"VIII"}
    blueprint = ndb.Key(urlsafe=blue_key).get()

    if blueprint.schema_version < SCHEMA_VERSION_CURRENT or blueprint.context_version < CONTEXT_VERSION_CURRENT:
       blueprint = process_blueprint(blueprint.blob_key, blueprint.title, blue_key).get()

    context = json.loads(blueprint.context)
    context['class'] = "Class-" + roman.get(round(math.log10(context['mass']),0),"?")
    context['blue_key'] = blue_key
    return render_template('view_blueprint.html', **context)

@app.route("/delete/<blue_key>")
def delete(blue_key):
    blue_key = ndb.Key(urlsafe=blue_key)
    blobstore.get(blue_key.get().blob_key).delete() # Why didn't project work here?
    blue_key.delete()
    return redirect(url_for('list'),303)
    

@app.route("/list/")
def list():
    query = Blueprint.query()
    blueprint_list = [{"blue_key":result.key.urlsafe(), "title":result.title} for result in query.iter(projection=[Blueprint.title])]
    return render_template("list.html", blueprint_list=blueprint_list)

@app.route("/old/")
def old_list():
    query = Blueprint.query(Blueprint.schema_version < SCHEMA_VERSION_CURRENT)
    blueprint_list = [{"blue_key":result.urlsafe(), "title":result.urlsafe()} for result in query.iter(keys_only=True)]
    return render_template("list.html", blueprint_list=blueprint_list)

#@app.route('/')
#def hello():
#    """Return a friendly HTTP greeting."""
#    return 'Hello World!'


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, Nothing at this URL.', 404


@app.errorhandler(500)
def application_error(e):
    """Return a custom 500 error."""
    return 'Sorry, unexpected error: {}'.format(e), 500
