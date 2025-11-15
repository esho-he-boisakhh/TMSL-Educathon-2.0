# appbackend.py
import os
import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from typing import List, Dict



FIREBASE_CRED_FILE = "firebase_credentials.json"
cred = credentials.Certificate(FIREBASE_CRED_FILE)
firebase_admin.initialize_app(cred)

db = firestore.client()


API_KEY = "AIzaSyAu7EaCkPbYZ4lacxmtaSkkaX261GN3EGs"


app = Flask(__name__)
CORS(app)


#
def doc_to_obj(doc):
    d = doc.to_dict() or {}
    d["id"] = doc.id
    return d


def safe_get_json(required=[]):
    data = request.get_json(silent=True) or {}
    for key in required:
        if key not in data:
            return None, jsonify({"error": f"Missing field: {key}"}), 400
    return data, None, None


#route test
@app.route("/")
def home():
    return jsonify({"message": "Backend running successfully"}), 200


#signup
@app.route("/signup", methods=["POST"])
def signup():
    data, err, code = safe_get_json(required=["email", "password"])
    if err:
        return err, code

    email = data["email"]
    password = data["password"]

    try:
        user = auth.create_user(email=email, password=password)

        db.collection("users").document(user.uid).set({
            "email": email,
            "displayName": email.split("@")[0],
            "skills": [],
            "bio": "",
            "created_at": firestore.SERVER_TIMESTAMP
        })

        return jsonify({"uid": user.uid}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#login
@app.route('/login', methods=['POST'])
def login():
    data, err, code = safe_get_json(required=["email", "password"])
    if err:
        return err, code

    email = data["email"]
    password = data["password"]

    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }

    try:
        resp = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}",
            json=payload
        ).json()

        if "error" in resp:
            return jsonify({"error": resp["error"]["message"]}), 400

        return jsonify({"uid": resp["localId"]}), 200

    except Exception as e:
        return jsonify({"error": "Server error"}), 500


#profile
@app.route("/users/<uid>", methods=["GET"])
def get_user(uid):
    try:
        doc = db.collection("users").document(uid).get()
        if not doc.exists:
            return jsonify({"error": "User not found"}), 404
        return jsonify(doc_to_obj(doc)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/users/<uid>", methods=["PUT"])
def update_user(uid):
    data = request.get_json() or {}
    try:
        db.collection("users").document(uid).update(data)
        return jsonify({"message": "User updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


#projects-
@app.route("/projects", methods=["POST"])
def create_project():
    data, err, code = safe_get_json(required=["name", "created_by"])
    if err:
        return err, code

    try:
        ref = db.collection("projects").add({
            "name": data["name"],
            "created_by": data["created_by"],
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"project_id": ref[1].id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/user/<uid>/projects", methods=["GET"])
def get_user_projects(uid):
    try:
        docs = (
            db.collection("projects")
            .where("created_by", "==", uid)
            .stream()
        )
        projects = [doc_to_obj(d) for d in docs]
        return jsonify({"projects": projects}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


#tasks
@app.route("/projects/<project_id>/tasks", methods=["GET"])
def get_tasks(project_id):
    try:
        docs = db.collection("projects").document(project_id).collection("tasks").stream()
        tasks = [doc_to_obj(d) for d in docs]
        return jsonify({"tasks": tasks}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

#status
@app.route("/projects/<project_id>/tasks", methods=["POST"])
def create_task(project_id):
    data, err, code = safe_get_json(required=["title", "status"])
    if err:
        return err, code

    try:
        ref = (
            db.collection("projects")
            .document(project_id)
            .collection("tasks")
            .add({
                "title": data["title"],
                "description": data.get("description", ""),
                "status": data["status"],
                "created_at": firestore.SERVER_TIMESTAMP
            })
        )
        return jsonify({"task_id": ref[1].id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#task update
@app.route("/projects/<project_id>/tasks/<task_id>", methods=["PUT"])
def update_task(project_id, task_id):
    try:
        data = request.get_json() or {}

        task_ref = (
            db.collection("projects")
            .document(project_id)
            .collection("tasks")
            .document(task_id)
        )

        task_doc = task_ref.get()

        if not task_doc.exists:
            return jsonify({'error': 'Task not found'}), 404

        current_status = task_doc.to_dict().get('status')
        new_status = data.get("status")

        #checking for status reversal prevention

        if current_status == 'Done' and new_status != 'Done':
            return jsonify({
                'error': 'Completed tasks cannot be changed back to other status'
            }), 400

        if current_status == 'In Progress' and new_status not in ['In Progress', 'Done']:
            return jsonify({
                'error': 'In Progress tasks cannot be reverted to Not Started or other status'
            }), 400

        #if allowed → update
        task_ref.update(data)

        return jsonify({"message": "Task updated"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#project delete
@app.route("/projects/<project_id>/tasks/<task_id>", methods=["DELETE"])
def delete_task(project_id, task_id):
    try:
        db.collection("projects").document(project_id).collection("tasks").document(task_id).delete()
        return jsonify({"message": "Task deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


#project progress
@app.route("/projects/<project_id>/progress", methods=["GET"])
def get_progress(project_id):
    try:
        docs = (
            db.collection("projects")
            .document(project_id)
            .collection("tasks")
            .stream()
        )

        tasks = [d.to_dict() for d in docs]
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") == "Done")

        percentage = (completed / total) * 100 if total else 0

        return jsonify({
            "total": total,
            "completed": completed,
            "progress": percentage
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#connection request sending
@app.route("/connect/send", methods=["POST"])
def send_connection():
    data, err, code = safe_get_json(required=["from", "to"])
    if err:
        return err, code

    try:
        ref = db.collection("connections").add({
            "from": data["from"],
            "to": data["to"],
            "status": "pending",
            "created_at": firestore.SERVER_TIMESTAMP
        })

        return jsonify({"request_id": ref[1].id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#connection request 
@app.route("/connect/requests/<uid>", methods=["GET"])
def get_requests(uid):
    try:
        docs = (
            db.collection("connections")
            .where("to", "==", uid)
            .where("status", "==", "pending")
            .stream()
        )
        requests = [doc_to_obj(d) for d in docs]
        return jsonify({"requests": requests}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/connect/accept/<req_id>", methods=["PUT"])
def accept_request(req_id):
    try:
        db.collection("connections").document(req_id).update({
            "status": "accepted",
            "responded_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "Connection accepted"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/connect/reject/<req_id>", methods=["PUT"])
def reject_request(req_id):
    try:
        db.collection("connections").document(req_id).update({
            "status": "rejected",
            "responded_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "Connection rejected"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#peer review
@app.route("/reviews", methods=["POST"])
def submit_review():
    data, err, code = safe_get_json(required=["reviewer", "reviewee", "team_id", "scores"])
    if err:
        return err, code

    try:
        ref = db.collection("peer_reviews").add({
            "reviewer": data["reviewer"],
            "reviewee": data["reviewee"],
            "team_id": data["team_id"],
            "scores": data["scores"],
            "comments": data.get("comments", ""),
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"review_id": ref[1].id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


#matchmaking
@app.route("/matchmaking", methods=["POST"])
def matchmaking():
    data, err, code = safe_get_json(required=["uid", "required_skills", "project_goal_roles", "target_role"])
    if err:
        return err, code

    uid = data["uid"]
    required_skills = data["required_skills"]
    project_goal_roles = data["project_goal_roles"]
    target_role = data["target_role"]

    try:
        #data fetch
        target_doc = db.collection("users").document(uid).get()
        if not target_doc.exists:
            return jsonify({"error": "User not found"}), 404
        
        target_data = target_doc.to_dict()
        target_skills = target_data.get("skills", [])
        
        target_vector = [skill.get("level", 0) for skill in target_skills]
        target_name = target_data.get("displayName", "")
        target_role = target_data.get("role", target_role)  
        
        #fetch skills and roles
        users_ref = db.collection("users").stream()
        all_vectors = []
        all_names = []
        all_roles = []

        for user_doc in users_ref:
            if user_doc.id == uid:
                continue  

            user_data = user_doc.to_dict()
            user_skills = user_data.get("skills", [])
            
            user_vector = [skill.get("level", 0) for skill in user_skills]
            all_vectors.append(user_vector)
            all_names.append(user_data.get("displayName", ""))
            all_roles.append(user_data.get("role", ""))
        
        #similarity calculation
        top_matches = compute_similarity(
            target_vector, 
            all_vectors, 
            all_names, 
            target_name, 
            all_roles, 
            target_role, 
            project_goal_roles
        )

        #top 3
        return jsonify({"matches": top_matches}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(debug=True)
