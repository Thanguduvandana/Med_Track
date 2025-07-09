from flask import Flask, render_template, request, redirect, url_for, session, flash
import boto3
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# --- AWS Setup ---
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
sns = boto3.client('sns', region_name='us-east-1')
sns_topic_arn = 'arn:aws:sns:us-east-1:904233124678:MedTrack'  # Replace with your actual topic ARN

# --- DynamoDB Tables ---
users_table = dynamodb.Table('Users')
appointments_table = dynamodb.Table('Appointments')
medications_table = dynamodb.Table('Medications')
records_table = dynamodb.Table('HealthRecords')

# --- Routes ---

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        role = request.form.get('role') or request.args.get('role')
        name = request.form['name']
        email = request.form['email']
        gender = request.form['gender']
        problem = request.form.get('health_problem', '')
        phone = request.form['phone']
        password = generate_password_hash(request.form['password'])

        existing = users_table.get_item(Key={'email': email}).get('Item')
        if existing:
            flash("User already exists!", "danger")
            return redirect(url_for('register'))

        user_item = {
            'email': email,
            'name': name,
            'password': password,
            'gender': gender,
            'phone': phone,
            'role': role
        }

        if role.lower() == 'doctor':
            user_item['specialization'] = problem
        else:
            user_item['health_problem'] = problem

        users_table.put_item(Item=user_item)

        try:
            sns.publish(
                TopicArn=sns_topic_arn,
                Message=f"New {role} registered: {name} ({email})",
                Subject="New User Registration"
            )
        except Exception as e:
            print(f"SNS Error: {e}")

        session['user'] = email
        session['role'] = role
        return redirect(url_for('dashboard') if role.lower() == 'patient' else url_for('doctors_dashboard'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_input = request.form['password']

        user = users_table.get_item(Key={'email': email}).get('Item')
        if user and check_password_hash(user['password'], password_input):
            session['user'] = email
            session['role'] = user['role']
            return redirect(url_for('doctors_dashboard') if user['role'].lower() == 'doctor' else url_for('dashboard'))

        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session or session['role'].lower() != 'patient':
        return redirect(url_for('login'))

    email = session['user']
    meds = medications_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('user_email').eq(email))['Items']
    appts = appointments_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('user_email').eq(email))['Items']
    records = records_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('patient_email').eq(email))['Items']

    return render_template('dashboard.html', email=email, medications=meds, appointments=appts, health_records=records)

@app.route('/doctors_dashboard')
def doctors_dashboard():
    if 'user' not in session or session['role'].lower() != 'doctor':
        return redirect(url_for('login'))

    email = session['user']
    appts = appointments_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('doctor_email').eq(email))['Items']
    records = records_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('doctor_email').eq(email))['Items']
    patients = users_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('role').eq('patient'))['Items']

    return render_template('doctors_dashboard.html', doctor=email, appointments=appts, patients=patients, health_records=records)

@app.route('/appointments', methods=['GET', 'POST'])
def appointments():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        item = {
            'id': str(uuid.uuid4()),
            'user_email': session['user'],
            'date': request.form['date'],
            'time': request.form['time'],
            'reason': request.form['reason'],
            'doctor_email': request.form['doctor_email']
        }
        appointments_table.put_item(Item=item)

        try:
            sns.publish(
                TopicArn=sns_topic_arn,
                Message=f"New appointment booked with Dr. {item['doctor_email']} on {item['date']} at {item['time']}.",
                Subject="New Appointment Notification"
            )
        except Exception as e:
            print(f"SNS Error: {e}")

        flash("Appointment booked and doctor notified.", "success")
        return redirect(url_for('dashboard'))

    return render_template('appointments.html')

@app.route('/add_medication', methods=['GET', 'POST'])
def add_medication():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        med = {
            'id': str(uuid.uuid4()),
            'user_email': session['user'],
            'name': request.form['name'],
            'dosage': request.form['dosage'],
            'frequency': request.form['frequency'],
            'notes': request.form['notes']
        }
        medications_table.put_item(Item=med)
        return redirect(url_for('dashboard'))

    return render_template('add_medication.html')

@app.route('/upload_record/<patient_email>', methods=['GET', 'POST'])
def upload_record(patient_email):
    if 'user' not in session or session['role'].lower() != 'doctor':
        return redirect(url_for('login'))

    if request.method == 'POST':
        record = {
            'id': str(uuid.uuid4()),
            'patient_email': patient_email,
            'doctor_email': session['user'],
            'title': request.form['title'],
            'description': request.form['description'],
            'upload_date': request.form.get('upload_date')
        }
        records_table.put_item(Item=record)
        return redirect(url_for('doctors_dashboard'))

    return render_template('upload_record.html', patient_email=patient_email)

@app.route('/view_record/<string:record_id>')
def view_record(record_id):
    if 'user' not in session:
        return redirect(url_for('login'))

    res = records_table.get_item(Key={'id': record_id})
    record = res.get('Item')
    return render_template('view_record.html', record=record)

@app.route('/health_records')
def health_records():
    if 'user' not in session or session['role'].lower() != 'patient':
        return redirect(url_for('login'))

    email = session['user']
    records = records_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('patient_email').eq(email))['Items']
    return render_template('health_records.html', records=records)

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/patient_details')
def patient_details():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = users_table.get_item(Key={'email': session['user']}).get('Item')
    return render_template('patient_details.html', patient=user)

if __name__ == '__main__':
    app.run(debug=True)
