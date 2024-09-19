from flask import Flask, render_template, request, redirect, url_for, session, flash, render_template_string, send_file, app, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_uploads import UploadSet, configure_uploads, DOCUMENTS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from string import punctuation
import uuid
import json
import string
import zipfile
import io
import qrcode
import os
import re
import fitz
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from datetime import timedelta
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from flask_mail import Mail, Message
import psycopg2
import sqlalchemy.dialects.postgresql
import tempfile
import random

app = Flask(__name__)
app.secret_key = '263FEA1F87FC3FAA'

app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://default:8iXjK9CPdhev@ep-polished-salad-a1bgg5k2.ap-southeast-1.aws.neon.tech:5432/verceldb?sslmode=require"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOADED_DOCS_DEST'] = os.path.join(os.getcwd(), 'static', 'uploads')
app.config['QR_CODES_DEST'] = os.path.join(os.getcwd(), 'static', 'qr')
ALLOWED_EXTENSIONS = {'pdf'}

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = ''
app.config['MAIL_PASSWORD'] = ''
mail = Mail(app)
s = URLSafeTimedSerializer('gm5CgA9Hxwufdy4BWV')

docs = UploadSet('docs', DOCUMENTS)
configure_uploads(app, docs)

def allowed_file(filename):
    return '.' in filename and filename[-4:].lower() == '.pdf'

db = SQLAlchemy(app)
migrate = Migrate(app, db)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), unique=True, nullable=False)
    password = db.Column(db.String(400), nullable=False)
    email = db.Column(db.String(400), unique=True, nullable=True)
    email_verified = db.Column(db.Boolean, default=False)
    webinars = db.relationship('Webinar', backref='creator', lazy=True)
    
class Webinar(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    webinar_name = db.Column(db.String(200), nullable=False)
    forms = db.relationship('Form', backref='event', lazy=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String, nullable=False)
    time = db.Column(db.String, nullable = False)
    organizer = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(1000))
    serial_number = db.Column(db.String, nullable = True)
    certified_participants = db.Column(db.Text, nullable=True)

class Form(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    webinar_id = db.Column(db.String(36), db.ForeignKey('webinar.id'), nullable=False)
    fields = db.Column(db.Text, nullable=False)  # JSON string of fields
    type = db.Column(db.String(36), nullable=False)
    active = db.Column(db.Boolean, default=True)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.String(36), db.ForeignKey('form.id'), nullable=False)
    data = db.Column(db.Text, nullable=False)

with app.app_context():
    db.create_all()

@app.before_request  # runs before FIRST request (only once)
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=60)

@app.route("/")
def home():
    return render_template('home.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    pattern = f"[{re.escape(string.punctuation)}]"
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        if len(username) < 4:
            flash('Username must be at least 4 characters long.', 'error')
            return redirect(url_for('register'))
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return redirect(url_for('register'))
        if not re.search("[a-z]", password) or not re.search("[A-Z]", password) or not re.search("[0-9]", password) or not re.search(pattern, password):
            flash('Password must contain at least one lowercase letter, one uppercase letter, one digit, and one special character.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('register'))
            
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password, email=email, email_verified=True)
        db.session.add(new_user)
        db.session.commit()

        # token = s.dumps(email, salt='email-confirm')
        # msg = Message('Confirm Email', sender='your_email@example.com', recipients=[email])
        # link = url_for('confirm_email', token=token, _external=True)
        # msg.body = f'Your confirmation link is {link}'
        # mail.send(msg)

        flash('Registration successful! Please check your email to confirm your account.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/confirm_email/<token>')
def confirm_email(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600)
        user = User.query.filter_by(username=email).first()
        if user:
            user.email_verified = True
            db.session.commit()
            flash('Email confirmed! You can now log in.', 'success')
            return redirect(url_for('login'))
    except SignatureExpired:
        flash('The confirmation link has expired.', 'error')
        return redirect(url_for('register'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            if user.email_verified:
                session['username'] = username
                flash('Login successful!', 'success')
                return redirect(url_for('home'))
            else:
                flash('Please verify your email first.', 'error')
                return redirect(url_for('login'))
        else:
            flash('Invalid credentials!', 'error')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form['email']
        user = User.query.filter_by(username=email).first()

        if user:
            token = s.dumps(email, salt='password-reset')
            msg = Message('Reset Your Password', sender='webinarsystem.app@gmail.com', recipients=[email])
            link = url_for('reset_password', token=token, _external=True)
            msg.body = f'Your password reset link is {link}'
            mail.send(msg)

            flash('A password reset link has been sent to your email.', 'success')
        else:
            flash('Invalid email address!', 'error')
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=["GET", "POST"])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset', max_age=3600)
        user = User.query.filter_by(username=email).first()

        if request.method == "POST":
            new_password = request.form['password']
            if len(new_password) < 8 or not re.search("[a-z]", new_password) or not re.search("[A-Z]", new_password) or not re.search("[0-9]", new_password) or not re.search("[@#$%^&+=!*]", new_password): #TODO: FIX THE SPECIAL CHAR
                flash('Password must meet the strength requirements.', 'error')
            else:
                hashed_password = generate_password_hash(new_password)
                user.password = hashed_password
                db.session.commit()
                flash('Your password has been reset. You can now log in.', 'success')
                return redirect(url_for('login'))
        return render_template('reset_password.html')
    except SignatureExpired:
        flash('The password reset link has expired.', 'error')
        return redirect(url_for('forgot_password'))

@app.route("/make_webinar", methods=["GET", "POST"])
def make_webinar():
    if 'username' not in session:
        flash('You need to be logged in to create a webinar.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        webinar_name = request.form['name']
        webinar_date = request.form['date']
        webinar_time = request.form['time']
        webinar_organizer = request.form['organizer']
        webinar_desc = request.form['description']
        user = User.query.filter_by(username=session['username']).first()
        webinar_id = str(uuid.uuid4())
        new_webinar = Webinar(id=webinar_id, webinar_name=webinar_name, creator=user, date = webinar_date, organizer = webinar_organizer, description = webinar_desc, time = webinar_time)
        db.session.add(new_webinar)
        db.session.commit()
        
        form_link = url_for('view_webinar', webinar_id=webinar_id, _external=True)
        return render_template('message.html', message='Webinar created! Access it at:', link=form_link)

    return render_template('make_webinar.html')

@app.route("/edit_webinar/<webinar_id>", methods=["GET", "POST"])
def edit_webinar(webinar_id):
    current_webinar = Webinar.query.get_or_404(webinar_id)
    if 'username' not in session or session['username'] != current_webinar.creator.username:
        flash('You are not authorized to edit the webinar.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        webinar_name = request.form['name']
        webinar_date = request.form['date']
        webinar_time = request.form['time']
        webinar_organizer = request.form['organizer']
        webinar_desc = request.form['description']
        user = User.query.filter_by(username=session['username']).first()
        current_webinar.webinar_name = webinar_name
        current_webinar.date = webinar_date
        current_webinar.time = webinar_time
        current_webinar.organizer = webinar_organizer
        current_webinar.description = webinar_desc
        db.session.commit()
        
        form_link = url_for('view_webinar', webinar_id=webinar_id, _external=True)
        return render_template('message.html',message='Webinar edited! Access it at:', link=form_link)

    return render_template('edit_webinar.html', webinar = current_webinar)

@app.route("/edit_form/<form_id>", methods=["GET", "POST"])
def edit_form(form_id):
    current_form = Form.query.get_or_404(form_id)
    if 'username' not in session or session['username'] != current_form.event.creator.username:
        flash('You are not authorized to edit the form.', 'error')
        return redirect(url_for('login'))

    form = Form.query.get_or_404(form_id)
    
    if request.method == 'POST':
        form.name = request.form['name']
        
        form_fields = []
        for key, value in request.form.items():
            if key.startswith('fields') and 'label' in key:
                index = key.split('[')[1].split(']')[0]
                label = value
                input_type = request.form.get(f'fields[{index}][type]', 'text')
                form_fields.append({'label': label, 'type': input_type})
        
        form.fields = json.dumps(form_fields)
        db.session.commit()
        
        form_link = url_for('view_form', form_id=form.id, _external=True)
        return render_template('message.html',message='Form updated! Access it at:', link=form_link)
    
    fields = json.loads(form.fields)
    return render_template('edit_form.html', form=form, fields=fields, form_type=form.type, enumerate=enumerate)

@app.route("/make_form/<webinar_id>/<form_type>", methods=["GET", "POST"])
def make_form(webinar_id, form_type):
    current_webinar = Webinar.query.get_or_404(webinar_id)
    if 'username' not in session or session['username'] != current_webinar.creator.username:
        flash('You are not authorized to make a form.', 'error')
        return redirect(url_for('login'))

    webinar = Webinar.query.get_or_404(webinar_id)
    
    if request.method == 'POST':
        form_name = request.form['name']
        
        form_fields = []
        for key, value in request.form.items():
            if key.startswith('fields') and 'label' in key:
                index = key.split('[')[1].split(']')[0]
                label = value
                input_type = request.form.get(f'fields[{index}][type]', 'text')
                form_fields.append({'label': label, 'type': input_type})
        
        form_id = str(uuid.uuid4())
        new_form = Form(id=form_id, name=form_name, webinar_id=webinar_id, fields=json.dumps(form_fields), type=form_type)
        db.session.add(new_form)
        db.session.commit()
        
        form_link = url_for('view_form', form_id=form_id, _external=True)
        return render_template('message.html',message='Form created! Access it at:', link=form_link)
    
    return render_template('make_form.html', webinar_id=webinar_id, form_type=form_type)

@app.route("/my_forms")
def my_forms():
    if 'username' not in session:
        flash('You need to be logged in to view your webinars.', 'error')
        return redirect(url_for('login'))
    
    user = User.query.filter_by(username=session['username']).first()
    webinars = Webinar.query.filter_by(creator=user).all()
    return render_template('my_forms.html', webinars=webinars)

@app.route('/webinar/<webinar_id>', methods=['GET'])
def view_webinar(webinar_id):
    webinar = Webinar.query.get_or_404(webinar_id)
    return render_template('view_webinar.html', webinar=webinar)

@app.route('/webinar/<webinar_id>/participants', methods=['GET'])
def view_participants(webinar_id):
    current_webinar = Webinar.query.get_or_404(webinar_id)
    if 'username' not in session or session['username'] != current_webinar.creator.username:
        flash('You are not authorized to view the webinar.', 'error')
        return redirect(url_for('login'))
    webinar = Webinar.query.get_or_404(webinar_id)
    register_forms = Form.query.filter(Form.event == webinar, Form.type == 'register').all()
    
    participants_data = []
    for form in register_forms:
        submissions = Submission.query.filter_by(form_id=form.id).all()
        for submission in submissions:
            data = json.loads(submission.data)
            participants_data.append({
                "form_name": form.name,
                "data": data
            })

    return render_template('view_participants.html', webinar=webinar, participants_data=participants_data)

@app.route("/generate_certificates/<webinar_id>", methods=["GET", "POST"])
def generate_certificates(webinar_id):
    webinar = Webinar.query.get_or_404(webinar_id)
    webinar_name = ''.join([i.upper() for i in webinar.webinar_name if i.isalpha()])
    webinar_organizer = ''.join([i.upper() for i in webinar.organizer if i.isalpha()])
    # print(webinar_name, webinar_organizer)
    webinar_serial=''
    if len(webinar_name)>=3 and len(webinar_organizer) >=3:
        webinar_serial = webinar_name[:3]+"."+webinar.date.replace('-','')+"."+webinar_organizer[:3]+".001"
    elif len(webinar_name)<3 and len(webinar_organizer) <3:
        webinar_serial = webinar_name+"."+webinar.date.replace('-','')+"."+webinar_organizer+".001"
    elif len(webinar_name)<3:
        webinar_serial = webinar_name+"."+webinar.date.replace('-','')+"."+webinar_organizer[:3]+".001"
    elif len(webinar_organizer)<3:
        webinar_serial = webinar_name[:3]+"."+webinar.date.replace('-','')+"."+webinar_organizer[:3]+".001"
    else:
        webinar_serial=''
    # print(webinar_serial)

    # Parsing every form datafield:
    set_of_fields = parse_form_fields(webinar)
                

    if 'username' not in session or session['username'] != webinar.creator.username:
        flash('You are not authorized to generate certificates.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        
        if 'template' not in request.files or request.files['template'].filename == '':
            flash('No template file uploaded', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))

        template_file = request.files['template']
        webinar_serial = request.form['serial_number']
        webinar.serial_number=webinar_serial
        db.session.commit()
        if template_file and allowed_file(template_file.filename):
            filename = secure_filename(template_file.filename)
            filepath = os.path.join('/tmp', filename)
            template_file.save(filepath)
        else:
            flash('Invalid file format. Only PDF files are allowed.', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))
        generate_qr = 'qr_generate' in request.form
        qr_code_path = None
        if generate_qr:
            qr_data = url_for('certif_verif', webinar_id=webinar.id, _external=True)
            qr = qrcode.make(qr_data)
            qr_code_path = os.path.join('/tmp', f"{webinar.id}.png")
            qr.save(qr_code_path)
        
        return redirect(url_for('generate_certificates_preview', webinar_id=webinar_id, file=filepath, filename=filename, generate_qr=generate_qr))
    return render_template('generate_certificates.html', webinar=webinar, webinar_serial=webinar_serial)

#TODO: Implement this page (name of certified participants)
@app.route("/certif_verif/<webinar_id>")
def certif_verif(webinar_id):
    webinar = Webinar.query.get_or_404(webinar_id)
    # Query to get participant details using certificate_id
    # participants = Participant.query.filter_by(certificate_id=certificate_id).all()
    # return render_template('certif_verif.html', participants=participants)
    current_webinar = Webinar.query.get_or_404(webinar_id)
    if 'username' not in session or session['username'] != current_webinar.creator.username:
        flash('You are not authorized to view the webinar.', 'error')
        return redirect(url_for('login'))
    webinar = Webinar.query.get_or_404(webinar_id)

    certified_participants = json.loads(webinar.certified_participants)
    participants_data = [{'form_name': name, 'data': {}} for name, email in certified_participants]

    return render_template('certif_verif.html', webinar=webinar, participants_data=participants_data)

@app.route("/generate_certificates_preview/<webinar_id>", methods=["GET", "POST"])
def generate_certificates_preview(webinar_id):
    webinar = Webinar.query.get_or_404(webinar_id)
    filepath = request.args.get('file')
    filename = request.args.get('filename').strip('.pdf')
    generate_qr = request.args.get('generate_qr', 'false').lower() == 'true'
    print(filepath)
    if not os.path.exists(filepath):
        return "File not found", 404

    # Convert the first page of the PDF to an image
    doc = fitz.open(filepath)
    page = doc.load_page(0)
    pix = page.get_pixmap()
    image_path = os.path.join('/tmp', f"{filename}_preview.png")
    pix.save(image_path)
    doc.close()

    set_of_fields = parse_form_fields(webinar)
    set_of_fields.add("Serial Number")
    print(set_of_fields)

    if request.method == 'POST':
        text_data = request.form['text_data']
        use_qr = request.form['use_qr']
        qr_data=''
        if use_qr == 'true':
            qr_data = request.form['qr_data']
        # text_data_list = json.loads(text_data)
        try:
            passing_grade = float(request.form['passing_grade'])
            print(passing_grade)
            passing_grade/=100
            if passing_grade >100 or passing_grade<0:
                raise ValueError
        except ValueError:
            flash('Invalid passing grade. Please enter a number between 0 and 100.', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))
        
        try:
            font_size = float(request.form['font_size'])
            if font_size <=0:
                raise ValueError
        except ValueError:
            flash('Invalid font size, please enter a number', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))
        # Generate certificates for participants in both sets
        in_memory_zip = io.BytesIO()
        input_method = request.form['input_method']
        
        participants = get_participant_data(webinar, passing_grade=passing_grade)
        # print("participants::: ", participants)
        webinar.certified_participants = json.dumps(list(participants))
        db.session.commit()
        serial_list = generate_serial_numbers(len(participants))
        qr_image_path, qr_data, qr_x, qr_y, qr_size = '', '', None, None, None
        if use_qr=='true':
            qr_image_path = os.path.join('/tmp', f"{webinar_id}.png")
            
    

        with zipfile.ZipFile(in_memory_zip, 'w') as zipf:
            series_counter = 0
            for name, email in participants:
                print(name, email)
                doc = fitz.open(filepath)
                page = doc[0]

                if input_method == 'placeholder':
                    placeholder = request.form['placeholder']
                    print('placeholder: ', placeholder)
                    placeholder_data = json.loads(placeholder)
                    for data in placeholder_data:
                        field = data['field']
                        placeholder_text = data['placeholder']
                        text_instances = page.search_for(placeholder_text)
                        for inst in text_instances:
                            rect = inst
                            page.add_redact_annot(rect)
                            page.apply_redactions()
                            text_width = stringWidth(name, "Helvetica", font_size)
                            text_x = rect.x0 + (rect.width - text_width) / 2 + 4
                            text_y = rect.y0 + rect.height / 2 + 4 
                            page.insert_text((text_x, text_y), get_specific_user_data(webinar,participants,field,name,email), font_size, color=(0, 0, 0))
                font = page.insert_font("Helvetica")
                text_data_list = json.loads(text_data)
                print(text_data)
                page_rect = page.rect
                max_x = page_rect.width  # Maximum width of the page
                max_y = page_rect.height
                for item in text_data_list:
                    text_x = item['x'] * max_x
                    text_y = item['y'] * max_y
                    print(text_x, text_y)
                    text = item['text']
                    if text == "Serial Number":
                        serial = webinar.serial_number
                        idx = serial.rfind('.')
                        serial = webinar.serial_number[:idx]
                        serial = serial + serial_list[series_counter]
                        len(participants)
                        series_counter+=1
                        page.insert_text((text_x, text_y), serial, font_size, color=(0, 0, 0))
                    else:
                        insert_data = get_specific_user_data(webinar, participants, text, name, email)
                        print(text)
                        print(insert_data)

                        page.insert_text((text_x, text_y), insert_data, font_size, color=(0, 0, 0))
                if os.path.exists(qr_image_path) and use_qr=='true':
                    qr_data = json.loads(request.form['qr_data'])
                    print(qr_data)
                    qr_x = qr_data['x']
                    qr_y = qr_data['y']
                    qr_size = qr_data['size'] * 0,8
                    with open(qr_image_path, "rb") as qr_image_file:
                        qr_image = qr_image_file.read()

                    page_rect = page.rect
                    x_coor = page_rect.width  # Maximum width of the page
                    y_coor = page_rect.height
                    qr_x *= x_coor
                    qr_y *= y_coor

                    # Define the rectangle for placing the QR code (fitz.Rect)
                    qr_rect = fitz.Rect(qr_x, qr_y, qr_x + qr_size, qr_y + qr_size)
                    
                    # Insert the QR code image into the PDF at the specified rectangle
                    try:
                        page.insert_image(qr_rect, stream=qr_image)
                    except Exception as e:
                        print(f"Failed to insert QR code: {e}")
                    print(f"QR code path: {qr_image_path}")

                pdf_buffer = io.BytesIO(doc.write())
                zipf.writestr(f"{name.replace(' ', '_')}_certificate.pdf", pdf_buffer.read())
                doc.close()
    
        in_memory_zip.seek(0)
    
        return send_file(in_memory_zip, download_name="certificates.zip", as_attachment=True)
    return render_template('generate_certificates_preview.html', webinar=webinar, image_url='/tmp/'+filename+'_preview.png',file=filepath, filename=filename, set_of_fields=set_of_fields, generate_qr=generate_qr)

@app.route('/form/<form_id>', methods=['GET'])
def view_form(form_id):
    form = Form.query.get_or_404(form_id)
    fields = json.loads(form.fields)
    return render_template('view_form.html', form=form, fields=fields)

@app.route('/form/<form_id>/submit', methods=['POST'])
def submit_form(form_id):
    form = Form.query.get_or_404(form_id)
    submission_data = json.dumps(request.form.to_dict())
    
    new_submission = Submission(form_id=form_id, data=submission_data)
    db.session.add(new_submission)
    db.session.commit()
    
    return render_template('submitted.html')

@app.route("/delete_form/<form_id>", methods=["POST"])
def delete_form(form_id):
    current_form = Form.query.get_or_404(form_id)
    if 'username' not in session or session['username'] != current_form.event.creator.username:
        flash('You are not authorized to delete the form.', 'error')
        return redirect(url_for('login'))
    
    form = Form.query.get_or_404(form_id)
    webinar = form.event 
    if session['username'] != webinar.creator.username:
        flash('You are not authorized to delete this form.', 'error')
        return redirect(url_for('view_webinar', webinar_id=webinar.id))

    submissions = Submission.query.filter_by(form_id=form.id).all()
    for submission in submissions:
        db.session.delete(submission)

    db.session.delete(form)
    db.session.commit()

    flash('Form deleted successfully.', 'success')
    return redirect(url_for('view_webinar', webinar_id=webinar.id))

@app.route("/delete_webinar/<webinar_id>", methods=["GET","POST"])
def delete_webinar(webinar_id):
    if 'username' not in session:
        flash('You need to be logged in to delete a form.', 'error')
        return redirect(url_for('login'))
    
    webinar = Webinar.query.get_or_404(webinar_id)
    if session['username'] != webinar.creator.username:
        flash('You are not authorized to delete this webinar.', 'error')
        return redirect(url_for('view_forms'))

    forms = Form.query.filter_by(webinar_id=webinar_id).all()
    for form in forms:
        submissions = Submission.query.filter_by(form_id=form.id).all()
        for submission in submissions:
            db.session.delete(submission)
        db.session.delete(form)

    db.session.delete(webinar)
    db.session.commit()

    flash('Webinar deleted successfully!', 'success')
    return redirect(url_for('my_forms'))

@app.route("/logout")
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

# Will return a set of form fields
def parse_form_fields(webinar):
    register_forms = Form.query.filter(Form.event == webinar, Form.type == 'register').all()
    absence_forms = Form.query.filter(Form.event == webinar, Form.type == 'absence').all()
    all_fields = set()

    for form in register_forms:
        fields=json.loads(form.fields)
        for field in fields:
            if field['type'] == 'file':
                pass
            else:
                all_fields.add(field['label'])
    
    for form in absence_forms:
        fields=json.loads(form.fields)
        for field in fields:
            if field['type'] == 'file':
                pass
            else:
                all_fields.add(field['label'])
    return all_fields

def get_form_fields(form):
    all_fields = set()
    fields=json.loads(form.fields)
    for field in fields:
        if field['type'] == 'file':
            pass
        else:
            all_fields.add(field['label'])
    return all_fields

def form_has_field(form, field_name):
    """
    Check if a form has a specific field by its name.
    """
    fields = get_form_fields(form)
    return field_name in fields

# TODO: get participant whole data
def get_specific_user_data(webinar, participants, field_name, name, email):

    # All forms for the webinar
    all_forms = Form.query.filter(Form.event == webinar).all()

    # Go through each participant and find the data
    found = False
    for form in all_forms:
        # Check if the form has the desired field
        if form_has_field(form, field_name):
            submissions = Submission.query.filter_by(form_id=form.id).all()
            for submission in submissions:
                data = json.loads(submission.data)
                count = 0
                for i in data:
                    if count == 0:
                        judul_name = i
                    if count == 1:
                        judul_email = i
                    count += 1
                # Check if this submission matches the user
                if data[judul_name] == name and data[judul_email] == email:
                    # If the field is in this submission, save it
                    if field_name in data:
                        return data[field_name]
    return None


def get_participant_data(webinar, passing_grade=0):
    register_forms = Form.query.filter(Form.event == webinar, Form.type == 'register').all()
    absence_forms = Form.query.filter(Form.event == webinar, Form.type == 'absence').all()
    registered = set()
    temp_attended = dict()
    participants = set()

    for form in register_forms:
        submissions = Submission.query.filter_by(form_id=form.id).all()
        for submission in submissions:
            data = json.loads(submission.data)
            count = 0
            for i in data:
                if count == 0:
                    name = i
                if count == 1:
                    email = i
                count += 1
            registered.add((data[name], data[email]))

    for form in absence_forms:
        submissions = Submission.query.filter_by(form_id=form.id).all()
        for submission in submissions:
            data = json.loads(submission.data)
            count = 0
            for i in data:
                if count == 0:
                    name = i
                if count == 1:
                    email = i
                count += 1
            person = (data[name], data[email])
            if person in temp_attended:
                temp_attended[person] += 1
            else:
                temp_attended[person] = 1
    
    # Calculate attendance percentage and determine who passed
    for person in registered:
        attendance_count = temp_attended.get(person, 0)
        total_absence_forms = len(absence_forms)
        if total_absence_forms > 0 and (attendance_count / total_absence_forms) >= passing_grade:
            participants.add(person)
        elif total_absence_forms == 0:
            participants.add(person)
    return participants

def generate_serial_numbers(participants_count):
    max_length = len(str(participants_count))
    serial_numbers = []
    
    for i in range(1, participants_count + 1):
        serial_number = str(i).zfill(max_length)
        serial_numbers.append(serial_number)
    
    return serial_numbers


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8081, debug=True)