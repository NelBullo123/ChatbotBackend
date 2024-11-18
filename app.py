import os
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from dotenv import load_dotenv
import cohere


# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Choose the correct configuration based on FLASK_ENV
if os.getenv('FLASK_ENV') == 'production':
    app.config.from_object('settings.ProductionConfig')
else:
    app.config.from_object('settings.DevelopmentConfig')

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
CORS(app, origins="https://chatbot32-e6oa.onrender.com", supports_credentials=True)
    
# SQLite database file path
DATABASE_FILE = os.getenv('DATABASE_FILE', 'database.db')

# Initialize Cohere API client
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
co = cohere.Client(COHERE_API_KEY)

# Test Cohere connection by making a simple request to the API
def check_cohere_connection():
    try:
        # Make a simple API call to verify the connection
        response = co.generate(
            model='command',
            prompt="Test",
            max_tokens=1
        )
        print("Cohere API is connected and active.")
    except Exception as e:
        print(f"Error connecting to Cohere API: {str(e)}")

# Call the function to check if Cohere is connected
check_cohere_connection()

# In-memory user data (for temporary memory of user)
user_memory = {}

# Function to create a database connection to SQLite
def get_db_connection():
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

# Create super user if it doesn't exist
def create_super_user():
    conn = get_db_connection()
    if conn is not None:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", ("ourchatbot32@gmail.com",))  # Super user email
        user_exists = cursor.fetchone()
        
        if not user_exists:
            hashed_password = generate_password_hash("chatbot32")  # Super user password
            cursor.execute("INSERT INTO users (email, password, history, last_question) VALUES (?, ?, ?, ?)", 
                           ("ourchatbot32@gmail.com", hashed_password, "", ""))  # Insert super user data
            conn.commit()
        
        conn.close()

# Create user table if it doesn't exist
def create_user_table():
    conn = get_db_connection()
    if conn is not None:
        cursor = conn.cursor()
        try:
            cursor.execute(''' 
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    history TEXT,
                    last_question TEXT
                )
            ''')
            conn.commit()

            # Create super user if needed
            create_super_user()

        finally:
            cursor.close()  # Explicitly close the cursor after use
        conn.close()
        
@app.route('/inspect', methods=['GET'])
def inspect_table():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users);")
        table_info = cursor.fetchall()
        conn.close()
        return jsonify({"table_info": table_info}), 200
    except Exception as e:
        return jsonify({"message": f"Error inspecting table: {str(e)}"}), 500

# Login route
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')

        print(f"Email: {email}, Password: {password}")  # Debugging print

        if not email or not password:
            return jsonify({'message': 'Missing email or password'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()

        if user and check_password_hash(user[2], password):  # Check if password matches
            token = jwt.encode({
                'user': email,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            }, app.config['SECRET_KEY'], algorithm="HS256")

            if email == "ourchatbot32@gmail.com":  # Check if the user is the super user
                return jsonify({'token': token, 'redirect': '/admin'}), 200

            return jsonify({'token': token}), 200
        else:
            return jsonify({'message': 'Invalid credentials'}), 401

    except Exception as e:
        print(f"Error: {e}")  # Log the exception in your server logs
        return jsonify({'message': 'An internal error occurred'}), 500



@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok"}), 200

# Register route
@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.json
        hashed_password = generate_password_hash(data['password'])
        email = data['email']

        conn = get_db_connection()
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user_exists = cursor.fetchone()
            if user_exists:
                return jsonify({"message": "User already exists"}), 400

            cursor.execute("INSERT INTO users (email, password, history, last_question) VALUES (?, ?, ?, ?)", 
                           (email, hashed_password, "", ""))
            conn.commit()
            conn.close()

        return jsonify({"message": "User registered successfully"}), 201
    except Exception as e:
        print(f"Error during registration: {e}")  # Log the error
        return jsonify({"message": "Internal Server Error", "error": str(e)}), 500


# Protected route
@app.route('/protected', methods=['GET'])
def protected():
    token = request.headers.get('Authorization').split()[1]
    try:
        jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return jsonify({"message": "Access granted"})
    except jwt.ExpiredSignatureError:
        return jsonify({"message": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"message": "Invalid token"}), 401

# Health check route
@app.route('/health', methods=['GET'])
def health_check():
    try:
        conn = get_db_connection()
        if conn is not None:
            conn.close()
            return jsonify({"message": "Database is running"}), 200
        else:
            return jsonify({"message": "Database connection failed"}), 500
    except Exception as e:
        return jsonify({"message": f"Error connecting to the database: {str(e)}"}), 500

@app.route('/admin/users', methods=['GET'])
def get_all_users():
    try:
        conn = get_db_connection()
        if conn is None:
            return jsonify({"message": "Failed to connect to the database"}), 500
        
        cursor = conn.cursor()

        cursor.execute("SELECT id, email FROM users") 
        users = cursor.fetchall()
        conn.close()

        if not users:
            return jsonify({"message": "No users found"}), 404

        # Prepare a list of user dictionaries
        users_list = [{"id": user[0], "email": user[1]} for user in users]
        return jsonify({"users": users_list}), 200
    except sqlite3.DatabaseError as db_error:
        print(f"Database Error: {db_error}")  # Log the database error
        return jsonify({"message": "Database error occurred", "error": str(db_error)}), 500
    except Exception as e:
        print(f"Error fetching users: {e}")  # Log any other exceptions
        return jsonify({"message": "An internal error occurred", "error": str(e)}), 500


    
# Chat route using Cohere
@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    user_email = request.json.get("email")  # Use email to identify users in memory

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Initialize user memory if not already stored
    if user_email not in user_memory:
        user_memory[user_email] = {"name": None, "preferences": [], "history": [], "last_question": None}

    # Save the current message as the user's last question
    user_memory[user_email]["last_question"] = user_message

    # Add the current message to the user's history
    user_memory[user_email]["history"].append(f"User: {user_message}")

    # Respond based on user's memory or intent
    response = handle_message(user_email, user_message)

    # Save the bot's response to history
    user_memory[user_email]["history"].append(f"Bot: {response}")

    # Save user history to SQLite
    save_user_history(user_email, user_message, response)

    return jsonify({"response": response})

# Handle the user's message and respond accordingly
def handle_message(user_email, user_message):
    user_data = user_memory[user_email]
    name = user_data.get("name")

    # Detect if the user is speaking in Tagalog based on keywords
    if is_tagalog(user_message):
        return handle_tagalog_response(user_email, user_message)

    # Check for Good Morning / Good Evening
    if "good morning" in user_message.lower():
        response = "Good morning! How can I assist you today?"
        if name:
            response = f"Good morning {name}! How can I assist you today?"
    
    elif "good evening" in user_message.lower():
        response = "Good evening! How can I assist you tonight?"
        if name:
            response = f"Good evening {name}! How can I assist you tonight?"
    
    # Default English responses
    elif "hello" in user_message.lower():
        response = "Hi there! How can I help you today?"
        if name:
            response = f"Hello {name}! How can I assist you today?"
        elif name is None:
            response = "Hi there! What's your name?"
    
    elif "bye" in user_message.lower():
        response = "Goodbye! Have a great day."

    elif "my name is" in user_message.lower():
        name = user_message.lower().split("my name is")[-1].strip()
        user_data["name"] = name
        response = f"Got it, {name}! I will remember your name."

    elif "preferences" in user_message.lower():
        response = f"Your current preferences are: {', '.join(user_data['preferences'])}"

    elif "history" in user_message.lower():
        history = user_data["history"]
        if history:
            response = "Here are your previous messages:\n" + "\n".join(history)
        else:
            response = "No history available."
    
    elif "last question" in user_message.lower():
        last_question = user_data.get("last_question", "No questions yet.")
        response = f"Your last question was: {last_question}"

    else:
        response = call_cohere_api(user_message)

    return response

# Check if the user's message is in Tagalog
def is_tagalog(message):
    tagalog_keywords = ['kamusta', 'magandang araw', 'salamat', 'paalam', 'kumusta', 'oo', 'hindi']
    return any(keyword in message.lower() for keyword in tagalog_keywords)

# Handle responses in Tagalog
def handle_tagalog_response(user_email, user_message):
    user_data = user_memory[user_email]
    name = user_data.get("name")

    if "kamusta" in user_message.lower() or "kumusta" in user_message.lower():
        response = "Kamusta! Paano kita matutulungan ngayon?"
        if name:
            response = f"Kamusta {name}! Paano kita matutulungan?"
        elif name is None:
            response = "Kamusta! Anong pangalan mo?"

    elif "magandang araw" in user_message.lower():
        response = "Magandang araw! Paano kita matutulungan?"
        if name:
            response = f"Magandang araw {name}! Paano kita matutulungan?"

    elif "salamat" in user_message.lower():
        response = "Walang anuman! Ano pa ang maitutulong ko?"
    
    else:
        return call_cohere_api(user_message)

    return response

# Call Cohere API for responses
def call_cohere_api(message):
    try:
        response = co.generate(
            model='command',
            prompt=message,
            max_tokens=150
        )
        return response.generations[0].text.strip()
    except Exception as e:
        return f"Error communicating with Cohere API: {str(e)}"

# Save user history to SQLite database
def save_user_history(email, user_message, bot_response):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        
        if user:
            new_history = user[3] + f"User: {user_message}\nBot: {bot_response}\n"
            cursor.execute("UPDATE users SET history = ? WHERE email = ?", (new_history, email))
            conn.commit()
        conn.close()

if __name__ == "__main__":
    create_user_table()
    app.run(debug=True)
