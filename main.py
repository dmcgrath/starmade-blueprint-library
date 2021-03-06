"""`main` is the top level module for the blueprint indexer Flask app)"""

from google.appengine.api import memcache, taskqueue, urlfetch
from google.appengine.datastore.datastore_query import Cursor
from google.appengine.ext import blobstore, ndb
from flask import Flask, render_template, request, make_response, redirect, url_for
from starmade import Blueprint, BlueprintAttachment
from struct import Struct
from werkzeug import parse_options_header
import access
import hashlib
import json
import logging
import math
import starmade
import StringIO
import urllib
import zipfile

app = Flask(__name__)

class Secrets(ndb.Model):
    """Datastore Entity for Private keys"""
    secret_key = ndb.StringProperty(indexed=False)

millnames=['', 'K', 'M', 'B', 'T']
def millify(n):
    """Converts a number into it's short scale abbreviation

    From here: http://stackoverflow.com/a/3155023/153407
    """
    n = float(n)
    millidx = max(0,min(len(millnames)-1,
                  int(math.floor(math.log10(abs(n))/3))))
    return '%.0f %s'%(n/10**(3*millidx),millnames[millidx])

@app.route("/")
def landing():
    return render_template("landing.html") 

@app.route("/upload")
def upload():
    version_id = request.environ["CURRENT_VERSION_ID"].split('.')[0]
    logging.info('App Version: '+version_id)
    user = ndb.Key(access.User, version_id).get()
    if user == None:
       return 'Forbidden', 403
    else:
        logging.info('User get: ' + user.display_name)

# Get bucket
    bucket = memcache.get('bucket')
    if bucket is None:
        bucket = ndb.Key(Secrets, 'blobstore').get().secret_key
        memcache.add('bucket', bucket, 36000)

    uploadUri = blobstore.create_upload_url('/submit',
                                            gs_bucket_name=bucket)
    return render_template('upload.html', uploadUri=uploadUri)

@app.route("/submit", methods=['POST'])
def submit():
    if request.method == 'POST':

        # Check reCaptcha before uploading
        recaptcha = request.form['g-recaptcha-response']
        url = 'https://www.google.com/recaptcha/api/siteverify'
        recaptcha_secrets = ndb.Key(Secrets, 'recaptcha').get()
        form_fields = {
            "secret": recaptcha_secrets.secret_key,
            "response": recaptcha,
            "remoteip": request.remote_addr
        }
        form_data = urllib.urlencode(form_fields)
        verify_recaptcha = urlfetch.fetch(url=url,
            payload=form_data,
            method=urlfetch.POST,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        verify_content = json.loads(verify_recaptcha.content)

        # Bypassing check since it seems like blobstore IP gets set here
        # making it impossible to confirm recaptcha in this manner :(
#        if (verify_content.get('success'), False):
#            return request.remote_addr+' Sorry, reCaptcha failed'+ verify_recaptcha.content, 403

        # reCaptcha has passed if we get to here - proceed with upload

        # TODO: Replace with real user stuff
        user_name = request.environ["CURRENT_VERSION_ID"].split('.')[0]
        f = request.files['file']
        power_recharge = starmade.valid_power(request.form['power_recharge'])
        power_capacity = starmade.valid_power(request.form['power_capacity'])
        blueprint_title = None
        header = f.headers['Content-Type']
        parsed_header = parse_options_header(header)
        blob_key = parsed_header[1]['blob-key']

        blue_key = process_blueprint(blob_key, blueprint_title, power_recharge,
                                     power_capacity, None, user_name)

        # process attachments
        taskqueue.add(url="/find_attachments", queue_name="deepdive",
                      params={"blob_key": blob_key, "blue_key": blue_key.urlsafe()})

        return render_template('finished_upload.html',
                               blue_key=blue_key.urlsafe())

def process_blueprint(blob_key, blueprint_title, power_recharge=0,
                      power_capacity=0, blue_key=None, user_name=None):
    blob_info = blobstore.get(blob_key)
    blob = blob_info.open()

    attached_count = 0

    with zipfile.ZipFile(file=blob, mode="r") as zip_file:
        for filename in (name for name in zip_file.namelist()
                         if name.endswith('/header.smbph')):
            if filename.count('/') == 1:
                blueprint_title = filename[:filename.find("/")].replace("_", " ")
                header_blob = zip_file.open(filename)
                blueprint = process_header(Blueprint, blob_key, header_blob,
                                           blueprint_title, power_recharge,
                                           power_capacity, blue_key)
            elif filename.count('/') == 2:
                attached_count += 1

        if user_name != None:
            blueprint.user = user_name
        blueprint.attached_count = attached_count

        blue_key = blueprint.put()

        #Save title for searching
        starmade.create_document(blueprint_title, blue_key.urlsafe())

        return blue_key

def process_header(Kind, blob_key, blob, blueprint_title, power_recharge=0,
                   power_capacity=0, blue_key=None, ancestor_key=None, paths=[]):

    header_blob = StringIO.StringIO(blob.read())

    version_struct = Struct('>i')
    ver = version_struct.unpack(header_blob.read(version_struct.size))[0]
    if ver > 65535:
        endian = '<'
        ver = ver<<24&0xFF000000|ver<<8&0xFF0000|ver>>8&0xFF00|ver>>24&0xFF
    else:
        endian = '>'
    header_struct = Struct(endian + 'I3f3fi')
    block_struct = Struct(endian + 'hi') # BlockID<short>, blockCount<int>

    result = []
    result = header_struct.unpack(header_blob.read(header_struct.size))

    entity_type = result[0]

    # -2 since core-only blueprint gives 2, -1 respectively.
    length = int(result[6] - result[3]) - 2
    width = int(result[4] - result[1]) - 2
    height = int(result[5] - result[2]) - 2

    context = {
       "title": blueprint_title,
       "version": ver,
       "entity": entity_type,
       "length": length,
       "width": width,
       "height": height,
       "power_recharge": {"base": 1},
       "power_capacity": {"base": 50000},
       "power_usage": {},
       "thrust": "None",
       "shields": {"capacity": 220, "recharge": 0},
       "systems" : {"medical": 0, "factory": 0}
    }

    ship_dimensions = context['length'] + context['width'] + context['height']
    element_count = result[7]
    element_list = []
    total_block_count = 0
    total_mass = 0
    power_recharge_rating = 0
    complex_systems = {"salvage": 0, "astrotech": 0, "power_drain": 0,
                       "power_supply": 0, "shield_drain": 0, "shield_supply": 0}

    for element in xrange(0, element_count):
        new_element = block_struct.unpack(header_blob.read(block_struct.size))
        element_list.append([new_element])
        block_id = new_element[0]
        block_count = new_element[1]
        total_block_count += block_count
        total_mass += block_count * starmade.NON_STANDARD_MASS.get(block_id, 0.1)
        if block_id == 2: # Power Block
            power_output = starmade.calc_power_output(block_count,
                                                      ship_dimensions)
            ideal_generator = round(power_output, 1)
            if power_recharge > ideal_generator or power_recharge == 0:
               context['power_recharge']['ideal_generator'] = ideal_generator
               context['power_efficieny_gauge'] = 100.0
               power_recharge_rating = ideal_generator
            else:
               power_efficieny_gauge = power_recharge / ideal_generator
               context['power_efficiency_gauge'] = round(power_efficieny_gauge * 100.0,1)
               context['power_recharge']['power_recharge'] = power_recharge
               power_recharge_rating = power_recharge
        elif block_id == 331: # Power Capacitor
            power_storage = starmade.calc_power_capacity(block_count)
            ideal_capacitor = round(power_storage, 1)
            if entity_type == 0:
                base_capacity = 50000
            else:
                base_capacity = 0
            context['ideal_capacitor'] = ideal_capacitor
            power_capacity -= base_capacity
            if power_capacity > ideal_capacitor or power_capacity <= 0:
               context['power_capacity']['ideal_capacitor'] = ideal_capacitor
            else:
               context['power_capacity']['power_capacity'] = power_capacity
               power_capacity_gauge = power_capacity / ideal_capacitor
               context['power_capacity_efficiency_gauge'] = round(power_capacity_gauge * 100.0,1)
        elif block_id == 8: # Thruster Block
            context['thrust'] = round(starmade.calc_thrust(block_count),1)
            context['power_usage']['thruster'] = round(-starmade.calc_thrust_power(block_count), 0)
        elif block_id == 3: # Shield Capacitor Block
            context['shields']['capacity'] = round(starmade.calc_shield_capacity(block_count), 0)
        elif block_id == 478: # Shield Recharger Block
            shield_power_standby = starmade.calc_shield_power(block_count)
            shield_power_active = starmade.calc_shield_power(block_count, True)
            shield_recharge = starmade.calc_shield_recharge(block_count)
            context['shields']['recharge'] = round(shield_recharge, 0)
            context['power_recharge']['shields'] = -round(shield_power_standby, 0)
            context['power_usage']['shield_recharge'] = -round(shield_power_active, 0)
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

    context['systems'] = {key:value for key,value
                          in context['systems'].iteritems() if value > 0}

    thrust_gauge = 0
    speed_coefficient = 0.5
    thrust = context['thrust']
    if thrust != 'None':
        thrust_gauge = starmade.thrust_rating(thrust, total_mass)
        speed_coefficient = round(starmade.calc_speed_coefficient(thrust, total_mass), 1)

    shields = context['shields']
    max_shield_capacity = starmade.calc_shield_capacity(total_block_count)
    shield_capacity_gauge = starmade.shield_rating(shields['capacity'],
                                                   max_shield_capacity)
    max_shield_recharge = starmade.calc_shield_recharge(total_block_count)
    shield_recharge_gauge = starmade.shield_rating(shields['recharge'],
                                                   max_shield_recharge)
    max_power_output = starmade.calc_power_output(total_block_count, 
                                                  ship_dimensions)
    power_recharge_gauge = starmade.shield_rating(power_recharge_rating,
                                                  max_power_output)

    if entity_type == 0:
        context['thrust_gauge'] = round(thrust_gauge * 100.0,1)
        context['speed_coefficient'] = speed_coefficient
    context['shield_capacity_gauge'] = round(shield_capacity_gauge * 100.0,1)
    context['shield_recharge_gauge'] = round(shield_recharge_gauge * 100.0,1)
    context['power_recharge_gauge'] = round(power_recharge_gauge * 100.0,1)
    context['power_recharge_sum'] = sum(context['power_recharge'].itervalues())
    context['power_capacity_sum'] = sum(context['power_capacity'].itervalues())

    if context['power_recharge_sum'] > 0:
        charge_time = float(context['power_capacity_sum']) / context['power_recharge_sum']
        context['idle_time_charge'] = round(charge_time, 1)
    else:
        context['idle_time_charge'] = "N/A"

    if ancestor_key == None:
        if blue_key == None:
            blueprint = Kind()
        else:
            blueprint = ndb.Key(urlsafe=blue_key).get()
            blueprint.schema_version = starmade.SCHEMA_VERSION_CURRENT
    else:
        blueprint = Kind(id=blue_key, parent=ancestor_key)
        blueprint.path = paths
        blueprint.depth = len(paths)

    blueprint.blob_key = blob_key
    blueprint.context = json.dumps(context)
    blueprint.elements = json.dumps(element_list)
    blueprint.element_count = element_count
    blueprint.length = length
    blueprint.width = width
    blueprint.height = height
    blueprint.max_dimension = max(length, width, height)
    blueprint.class_rank = int(max(math.log10(total_mass), 0))
    blueprint.title = blueprint_title
    blueprint.power_recharge = power_recharge
    blueprint.power_capacity = power_capacity
    blueprint.systems = context['systems'].keys()

    header_blob.seek(0)
    blueprint.header_hash = hashlib.md5(header_blob.read()).hexdigest()

    return blueprint

@app.route("/blueprint/<blob_key>")
def download_blueprint(blob_key):
    blob_info = blobstore.get(blob_key)
    response = make_response(blob_info.open().read())
    response.headers['Content-Type'] = blob_info.content_type
    return response

@app.route("/view/<blue_key>")
def view(blue_key):
    roman = {-1: "N", 0: "N", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
             6: "VI", 7: "VII", 8: "VIII"}
    blueprint_key = ndb.Key(urlsafe=blue_key)
    blueprint = blueprint_key.get()
    schema_version = blueprint.schema_version
    if schema_version < starmade.SCHEMA_VERSION_CURRENT:
       power_recharge = starmade.valid_power(blueprint.power_recharge)
       power_capacity = starmade.valid_power(blueprint.power_capacity)
       blueprint = process_blueprint(blueprint.blob_key, blueprint.title,
                                     power_recharge, power_capacity,
                                     blue_key).get()

    context = json.loads(blueprint.context)
    context['class'] = "Class-" + roman.get(round(math.log10(context['mass']), 0), "?")
    context['blue_key'] = blue_key

    user = ndb.Key(access.User, blueprint.user).get()

    context['profile_url'] = user.profile_url
    context['display_name'] = user.display_name

    query = BlueprintAttachment.query(ancestor=blueprint_key)
    query = query.filter(BlueprintAttachment.depth == 1)
    query = query.order(-BlueprintAttachment.class_rank)
    
    attachment_list = [{"blue_key": r.key.urlsafe(), "title": r.title,
                        "header_hash": r.header_hash,
                        "class_rank": r.class_rank} for r in query.iter()]
    context['attachment_list'] = attachment_list

    if attachment_list != None:
        context['missing_count'] = blueprint.attached_count - len(attachment_list)
    else:
        context['missing_count'] = 0

    return render_template('view_blueprint.html', **context)

@app.route("/view_attachment/<blue_key>")
def view_attachment(blue_key):
    roman = {-1: "N", 0: "N", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
             6: "VI", 7: "VII", 8: "VIII"}
    attachment_key = ndb.Key(urlsafe=blue_key)
    blueprint = attachment_key.get()
    parent_blueprint = attachment_key.parent().get()
    schema_version = blueprint.schema_version
    
    # TODO: Need to add schema updating logic that works for attachments

    context = json.loads(blueprint.context)
    context['class'] = "Class-" + roman.get(round(math.log10(context['mass']), 0), "?")
    context['blue_key'] = blue_key
    context['parent'] = parent_blueprint.key.urlsafe()
    context['parent_title'] = parent_blueprint.title

    next_depth = blueprint.depth + 1
    query = BlueprintAttachment.query(ancestor=parent_blueprint.key)
    query = query.filter(BlueprintAttachment.path == '/' + blueprint.title)
    query = query.filter(BlueprintAttachment.depth == next_depth)
    query = query.order(-BlueprintAttachment.class_rank)
    
    attachment_list = [{"blue_key": r.key.urlsafe(), "class_rank": r.class_rank, 
                        "title": r.title,
                        "header_hash": r.header_hash} for r in query.iter()]
    context['attachment_list'] = attachment_list    
    
    return render_template('view_attachment.html', **context)

@app.route("/delete/<blue_key>", methods=['POST'])
def delete(blue_key):
    blue_key = ndb.Key(urlsafe=blue_key)
    blobstore.get(blue_key.get().blob_key).delete()
    blue_key.delete()
    return redirect(url_for('list',cursor_token=""),303)

@app.route("/list/")
def list_new():
    return list()

@app.route("/list/<cursor_token>")
def list(cursor_token=None):
    query = Blueprint.query(projection=[Blueprint.title, Blueprint.class_rank])
    if cursor_token != None:
       curs = Cursor(urlsafe=cursor_token)
    else:
       curs = None

    list_query, next_curs, more_flag = query.fetch_page(50, start_cursor=curs)

    blueprint_list = [{"blue_key": r.key.urlsafe(),
                       "title": r.title,
                       "class_rank": r.class_rank} for r in list_query]
    return render_template("list.html", blueprint_list=blueprint_list,
                           next_curs=next_curs.urlsafe(), more_flag=more_flag)

@app.route("/old/")
def old_list():
    query = Blueprint.query(Blueprint.schema_version < starmade.SCHEMA_VERSION_CURRENT)
    blueprint_list = [{"blue_key":result.urlsafe()} for result in query.iter(keys_only=True)]
    return render_template("old.html", blueprint_list=blueprint_list)

@app.route("/search/")
def search():
    return render_template('search.html')

@app.route("/search/list/")
def search_list_new():
    return search_list()

@app.route("/search/list/<cursor_token>")
def search_list(cursor_token=None):
    search_type = request.args['search_type']
    filter_op = request.args['filter_op']

    try:
        filter_value = int(request.args['filter_value'])
        if filter_value < 0:
            filter_value = 0
        elif filter_value > 9999:
            filter_Value = 9999
    except ValueError:
        # somehow an invalid value was returned
        return redirect(url_for('search'),303)

    projection=[Blueprint.title, Blueprint.class_rank]
    query = Blueprint.query()
    static_class = None

    if search_type == "class_rank":
        if filter_op == "lesser_equal":
            query = query.filter(Blueprint.class_rank <= filter_value)
        elif filter_op == "equal":
            projection=[Blueprint.title]
            static_class = filter_value
            query = query.filter(Blueprint.class_rank == filter_value)
        elif filter_op == "greater_equal":
            query = query.filter(Blueprint.class_rank >= filter_value)
        else:
            # someone edited the page
            return redirect(url_for('search'),303)
    elif search_type == "simple":
        if filter_op == "lesser_equal":
            query = query.filter(Blueprint.element_count <= filter_value)
        elif filter_op == "equal":
            query = query.filter(Blueprint.element_count == filter_value)
        elif filter_op == "greater_equal":
            query = query.filter(Blueprint.element_count >= filter_value)
        else:
            # someone edited the page
            return redirect(url_for('search'),303)
    elif search_type == "dimensions":
        if filter_op == "lesser_equal":
            query = query.filter(Blueprint.max_dimension <= filter_value)
        elif filter_op == "equal":
            query = query.filter(Blueprint.max_dimension == filter_value)
        elif filter_op == "greater_equal":
            query = query.filter(Blueprint.max_dimension >= filter_value)
        else:
            # someone edited the page
            return redirect(url_for('search'),303)
    else:
        # someone edited the page
        return redirect(url_for('search'),303)

    if cursor_token != None:
       curs = Cursor(urlsafe=cursor_token)
    else:
       curs = None

    list_query, next_curs, more_flag = query.fetch_page(50, start_cursor=curs,
                                                        projection=projection)

    if static_class is None:
        blueprint_list = [{"blue_key": r.key.urlsafe(),
                           "title": r.title,
                           "class_rank": r.class_rank} for r in list_query]
    else:
        blueprint_list = [{"blue_key": r.key.urlsafe(),
                           "title": r.title,
                           "class_rank": static_class} for r in list_query]

    return render_template("search_results.html", blueprint_list=blueprint_list,
                           next_curs=next_curs.urlsafe(), more_flag=more_flag,
                           search_type=search_type, filter_op=filter_op,
                           filter_value=filter_value)

@app.route("/find_attachments", methods=['POST'])
def find_attachments():
    MAX_TASKS = 10
    blob_key = request.form['blob_key']
    blue_key = request.form['blue_key']

    blob_info = blobstore.get(blob_key)
    blob = blob_info.open()

    task_bundle = []
    with zipfile.ZipFile(file=blob, mode="r") as zip_file:
        for filename in (name for name in zip_file.namelist()
                         if name.endswith('/header.smbph')
                            and name.count('/') > 1):
            attachment_title = filename
            parent_path = filename[filename.find('/'):filename.rfind('/')]
            parent_depth = parent_path.count('/')
            header_blob = zip_file.open(filename)
            attachment = {"path": parent_path,
                          "header": header_blob.read().encode("base64")}

            task_bundle.append(attachment)
            if len(task_bundle) >= MAX_TASKS:
                payload = json.dumps({"blue_key": blue_key, "tasks": task_bundle})
                taskqueue.add(url="/add_attachments", queue_name="expand",
                              payload=payload)
                task_bundle = []

    if len(task_bundle) > 0:
        payload = json.dumps({"blue_key": blue_key, "tasks": task_bundle})
        taskqueue.add(url="/add_attachments", queue_name="expand",
                      payload=payload)

    return 'OK', 200

@app.route("/add_attachments", methods=['POST'])
def add_attachments():
    task_bundle = json.loads(request.data)
    blue_key = task_bundle["blue_key"]
    ancestor_key = ndb.Key(urlsafe=blue_key)

    attachments = []
    for task in task_bundle['tasks']:
        path = task['path']
        title = path[1:]
        parent_paths = []
        partial_path = ""
        for part in title.split('/'):
            partial_path += '/' + part
            parent_paths.append(partial_path)
        header_blob = task['header'].decode("base64")
        header_file = StringIO.StringIO(header_blob)
        blueprint = process_header(BlueprintAttachment, "", header_file, title,
                                   power_recharge=0, power_capacity=50000,
                                   blue_key=path, ancestor_key=ancestor_key,
                                   paths=parent_paths)
        attachments.append(blueprint)

    # TODO: transaction
    attachment_keys = ndb.put_multi(attachments)
    # Need to catch errors here and retry

    return 'OK', 200

@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, Nothing at this URL.', 404


@app.errorhandler(500)
def application_error(e):
    """Return a custom 500 error."""
    return 'Sorry, unexpected error: {}'.format(e), 500
