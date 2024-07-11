from flask import Flask, render_template, request, redirect, url_for, session, flash, render_template_string, send_file, app
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_uploads import UploadSet, configure_uploads, DOCUMENTS
from flask_sqlalchemy import SQLAlchemy
import uuid
import json
import zipfile
import io
import os
import fitz
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from datetime import timedelta
import psycopg2
import sqlalchemy.dialects.postgresql
import tempfile

app = Flask(__name__)
app.secret_key = '263FEA1F87FC3FAA'

app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://default:8iXjK9CPdhev@ep-polished-salad-a1bgg5k2.ap-southeast-1.aws.neon.tech:5432/verceldb?sslmode=require"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOADED_DOCS_DEST'] = os.path.join(os.getcwd(), 'static', 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
docs = UploadSet('docs', DOCUMENTS)
configure_uploads(app, docs)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
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

class Form(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    webinar_id = db.Column(db.String(36), db.ForeignKey('webinar.id'), nullable=False)
    fields = db.Column(db.Text, nullable=False)  # JSON string of fields
    type = db.Column(db.String(36), nullable=False)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.String(36), db.ForeignKey('form.id'), nullable=False)
    data = db.Column(db.Text, nullable=False)

with app.app_context():
    db.create_all()

@app.before_request  # runs before FIRST request (only once)
def make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(minutes=5)

@app.route("/")
def home():
    return render_template('home.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials!', 'error')
            return redirect(url_for('login'))
    return render_template('login.html')

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
        return render_template('message.html','Webinar edited! Access it at:', link=form_link)

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
        return render_template('message.html','Form updated! Access it at:', link=form_link)
    
    fields = json.loads(form.fields)
    return render_template('edit_form.html', form=form, fields=fields, form_type=form.type, enumerate=enumerate)

@app.route("/make_form/<webinar_id>/<form_type>", methods=["GET", "POST"])
def make_form(webinar_id, form_type):
    if 'username' not in session:
        flash('You need to be logged in to create a form.', 'error')
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
        return render_template('message.html','Form created! Access it at:', link=form_link)
    
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

@app.route("/generate_certificates/<webinar_id>", methods=["GET", "POST"])
def generate_certificates(webinar_id):
    webinar = Webinar.query.get_or_404(webinar_id)

    if 'username' not in session or session['username'] != webinar.creator.username:
        flash('You are not authorized to generate certificates.', 'error')
        return redirect(url_for('login'))
    

    if request.method == 'POST':
        try:
            passing_grade = float(request.form['passing_grade'])
            passing_grade/=100
            if passing_grade >100 or passing_grade<0:
                raise ValueError
        except ValueError:
            flash('Invalid passing grade. Please enter a number between 0 and 100.', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))

        if 'template' not in request.files or request.files['template'].filename == '':
            flash('No template file uploaded', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))

        template_file = request.files['template']
        if template_file and allowed_file(template_file.filename):
            template_bytes = template_file.read()
        else:
            flash('Invalid file format. Only PDF files are allowed.', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))
        
        try:
            font_size = float(request.form['font_size'])
            if font_size <=0:
                raise ValueError
        except ValueError:
            flash('Invalid font size, please enter a number', 'error')
            return redirect(url_for('view_webinar', webinar_id=webinar_id))

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
        
        # Generate certificates for participants in both sets
        in_memory_zip = io.BytesIO()
        input_method = request.form['input_method']
        x_coordinate = float(request.form['x_coordinate']) if input_method == 'coordinates' else None
        y_coordinate = float(request.form['y_coordinate']) if input_method == 'coordinates' else None
        
        with zipfile.ZipFile(in_memory_zip, 'w') as zipf:
            for name, email in participants:
                doc = fitz.open(stream=template_bytes, filetype="pdf")
                page = doc[0]

                if input_method == 'placeholder':
                    placeholder = request.form['placeholder']
                    text_instances = page.search_for(placeholder)
                    for inst in text_instances:
                        rect = inst
                        page.add_redact_annot(rect)
                        page.apply_redactions()
                        text_width = stringWidth(name, "Helvetica", font_size)
                        text_x = rect.x0 + (rect.width - text_width) / 2 + 4
                        text_y = rect.y0 + rect.height / 2 + 4 
                        page.insert_text((text_x, text_y), name, font_size, color=(0, 0, 0))
                elif x_coordinate is not None and y_coordinate is not None:
                    if x_coordinate<0 or y_coordinate<0:
                        flash('Invalid coordinates.', 'error')
                        return redirect(url_for('generate_certificates', webinar_id=webinar_id))
                    font = page.insert_font("Helvetica")
                    text_x = x_coordinate - (stringWidth(name, "Helvetica", font_size)/2)
                    text_y = y_coordinate
                    page.insert_text((text_x, text_y), name, font_size, color=(0, 0, 0))

                pdf_buffer = io.BytesIO(doc.write())
                zipf.writestr(f"{name.replace(' ', '_')}_certificate.pdf", pdf_buffer.read())
    
        in_memory_zip.seek(0)
    
        return send_file(in_memory_zip, download_name="certificates.zip", as_attachment=True)
    return render_template('generate_certificates.html', webinar=webinar)

@app.route("/generate_certificates_preview/<webinar_id>", methods=["POST"])
def generate_certificates_preview(webinar_id):
    if 'template' not in request.files or request.files['template'].filename == '':
        return "No template file uploaded", 400

    template_file = request.files['template']
    if not allowed_file(template_file.filename):
        return "Invalid file format. Only PDF files are allowed.", 400

    template_bytes = template_file.read()

    try:
        x_coordinate = float(request.form['x_coordinate'])
        y_coordinate = float(request.form['y_coordinate'])
        if x_coordinate < 0 or y_coordinate < 0:
            raise ValueError
    except ValueError:
        flash('Invalid coordinates', 'error')
        return redirect(url_for('generate_certificates', webinar_id=webinar_id))
    
    try:
        font_size = float(request.form['font_size'])
        if font_size <=0:
            raise ValueError
    except ValueError:
        flash('Invalid font size, please enter a number', 'error')
        return redirect(url_for('generate_certificates', webinar_id=webinar_id))

    doc = fitz.open(stream=template_bytes, filetype="pdf")
    page = doc[0]

    font = page.insert_font("Helvetica")
    text_x = x_coordinate - (stringWidth("Your Text Here", "Helvetica", font_size)/2)
    text_y = y_coordinate
    page.insert_text((text_x, text_y), "Your Text Here", font_size, color=(0, 0, 0))

    pdf_buffer = io.BytesIO(doc.write())
    return send_file(io.BytesIO(pdf_buffer.getvalue()), mimetype='application/pdf')

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
    
    return 'Form submitted successfully!'

@app.route("/delete_form/<form_id>", methods=["POST"])
def delete_form(form_id):
    current_form = Form.query.get_or_404(form_id)
    if 'username' not in session or session['username'] != current_form.event.creator.username:
        flash('You are not authorized to delete the form.', 'error')
        return redirect(url_for('login'))
    
    form = Form.query.get_or_404(form_id)
    webinar = form.event  # Get the associated webinar
    if session['username'] != webinar.creator.username:
        flash('You are not authorized to delete this form.', 'error')
        return redirect(url_for('view_webinar', webinar_id=webinar.id))

    # Delete all submissions related to this form
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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8081, debug=True)