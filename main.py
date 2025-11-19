from datetime import datetime
from flask import Flask, jsonify, render_template, request
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import sqlite3

app = Flask(__name__)

db = sqlite3.connect("data.db")
cursor = db.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS fys (
	id INTEGER PRIMARY KEY UNIQUE NOT NULL,
	name TEXT NOT NULL,
	status TEXT NOT NULL DEFAULT "open"
)""")
db.commit()
db.close()

def check_fields(form, required_fields):
	for i in required_fields:
		if i not in form.keys():
			return {
				"error": "Not submitted",
				"field": i
			}
	for i in required_fields:
		if not form.get(i):
			return {
				"error": "empty",
				"field": i
			}
	return False

@app.route("/", methods=["GET"])
def index():
	return render_template("index.html")

@app.route("/fy", methods=["POST", "GET", "PATCH", "DELETE"])
def fy():
	db = sqlite3.connect("data.db")
	cursor = db.cursor()
	cursor.row_factory = sqlite3.Row
	if request.method == "POST":
		required_fields = ["fy_name"]
		error = check_fields(request.form, required_fields)
		if error:
			db.close()
			return jsonify(error), 400
		fy_name = request.form.get("fy_name").strip()
		cursor.execute("SELECT * FROM fys WHERE name=?", (fy_name,))
		row = cursor.fetchone()
		if row:
			db.close()
			return jsonify({
				"error": "Journal already exists",
				"id": row["id"]
			}), 400
		cursor.execute("INSERT INTO fys (name) VALUES(?)", (fy_name,))
		cursor.execute("SELECT * FROM fys WHERE name=?", (fy_name,))
		row = cursor.fetchone()
		row = dict(row)
		cursor.execute(f"""CREATE TABLE IF NOT EXISTS journal_{row.get("id")} (
			id INTEGER PRIMARY KEY UNIQUE NOT NULL,
			date TEXT NOT NULL,
			ac_debited TEXT NOT NULL,
			ac_credited TEXT NOT NULL,
			amount INTEGER NOT NULL,
			description TEXT NOT NULL
		)""")
		db.commit()
		db.close()
		return jsonify({
			"success": 1,
			"row": row
		}), 200
	elif request.method == "GET":
		cursor.execute("SELECT * FROM fys")
		rows = cursor.fetchall()
		rows = [dict(row) for row in rows]
		db.close()
		fy_q = request.args.get("fy_q")
		if fy_q:
			vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
			tfidf_matrix = vectorizer.fit_transform([row["name"].lower() for row in rows])
			query_vec = vectorizer.transform([fy_q.strip().lower()])
			sim_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()
			rows = [rows[i] for i in sim_scores.argsort()[::-1] if sim_scores[i] >= 0.3]
		return jsonify(rows), 200
	elif request.method == "PATCH":
		error = check_fields(request.form, ["id", "purpose"])
		if error:
			db.close()
			return jsonify(error), 400
		purpose = request.form.get("purpose").strip()
		id = request.form.get("id").strip()
		if purpose == "update_text":
			error = check_fields(request.form, ["fy_name"])
			if error:
				db.close()
				return jsonify(error), 400
			cursor.execute("SELECT * FROM fys WHERE id=?", (id,))
			row = cursor.fetchone()
			if not row:
				db.close()
				return jsonify({"error": "Invalid id"}), 400
			fy_name = request.form.get("fy_name").strip()
			cursor.execute("SELECT * FROM fys WHERE name=? AND id!=?", (fy_name, id))
			row = cursor.fetchone()
			if row:
				db.close()
				return jsonify({
					"error": "Journal already exists",
					"id": row["id"]
				}), 400
			cursor.execute("UPDATE fys SET name=? WHERE id=?", (fy_name, id))
			db.commit()
			db.close()
			return jsonify({"success": 1}), 200
		elif purpose == "update_status":
			cursor.execute("SELECT * FROM fys WHERE id=?", (id,))
			row = cursor.fetchone()
			if not row:
				db.close()
				return jsonify({"error": "Invalid id"}), 400
			status = dict(row).get("status")
			cursor.execute("UPDATE fys SET status=? WHERE id=?", ("closed" if status == "open" else "open", id))
			db.commit()
			db.close()
			return jsonify({"success": 1, "status": "closed" if status == "open" else "open"}), 200
		else:
			return jsonify({"error": "Invalid purpose"}), 400
	elif request.method == "DELETE":
		error = check_fields(request.form, ["id"])
		if error:
			db.close()
			return jsonify(error), 400
		id = request.form.get("id").strip()
		cursor.execute("SELECT * FROM fys WHERE id=?", (id,))
		row = cursor.fetchone()
		if not row:
			db.close()
			return jsonify({"error": "Invalid id"}), 400
		row = dict(row)
		cursor.execute("DELETE FROM fys WHERE id=?", (id,))
		cursor.execute(f"DROP TABLE journal_{row.get("id")}")
		db.commit()
		db.close()
		return jsonify({"success": 1}), 200

@app.route("/journal/<id>", methods=["POST", "GET"])
def journal(id):
	db = sqlite3.connect("data.db")
	cursor = db.cursor()
	cursor.row_factory = sqlite3.Row
	cursor.execute("SELECT * FROM fys WHERE id=?", (id,))
	row = cursor.fetchone()
	if not row:
		db.close()
		return jsonify({"error": "Invalid id"}), 400
	row = dict(row)
	if request.method == "GET":
		cursor.execute(f"SELECT * FROM journal_{row.get("id")}")
		rows = cursor.fetchall()
		rows = [dict(row) for row in rows]
		total = 0
		if rows:
			cursor.execute(f"SELECT SUM(amount) FROM journal_{row.get("id")}")
			total = cursor.fetchone()
			total = total[0] if total and total[0] is not None else 0
		db.close()
		return jsonify({
			"rows": rows,
			"total": total,
			"fy_name": row.get("name")
		}), 200
	elif request.method == "POST":
		required_fields = ["date", "ac_debited", "ac_credited", "amount", "description"]
		balance = {}
		for i in range(0, len(request.json)):
			error = check_fields(request.json[i], required_fields)
			if error:
				error["index"] = i
				return jsonify(error), 400
			try:
				amount = float(request.json[i]["amount"])
			except:
				db.close()
				return jsonify({
					"error": "invalid amount",
					"field": "amount",
					"index": i
				}), 400
			if amount <= 0:
				db.close()
				return jsonify({
					"error": "invalid amount",
					"field": "amount",
					"index": i
				})
			date = request.json[i].get("date")
			try:
				datetime.strptime(date, "%Y-%m-%d")
			except:
				db.close()
				return jsonify({
					"error": "invalid date",
					"field": "date",
					"index": i
				}), 400
		cursor.execute(f"DROP TABLE journal_{row.get("id")}");
		cursor.execute(f"""CREATE TABLE IF NOT EXISTS journal_{row.get("id")} (
			id INTEGER PRIMARY KEY UNIQUE NOT NULL,
			date TEXT NOT NULL,
			ac_debited TEXT NOT NULL,
			ac_credited TEXT NOT NULL,
			amount INTEGER NOT NULL,
			description TEXT NOT NULL
		)""")
		for i in request.json:
			cursor.execute(f"INSERT INTO journal_{row.get("id")} (date, ac_debited, ac_credited, amount, description) VALUES(?, ?, ?, ?, ?)",
				(i["date"].strip(), i["ac_debited"].strip(), i["ac_credited"].strip(), i["amount"].strip(), i["description"].strip()))
		db.commit()
		db.close()
		return jsonify({"success": 1}), 200

@app.route("/ledger/<id>", methods=["GET"])
def ledger(id):
	db = sqlite3.connect("data.db")
	cursor = db.cursor()
	cursor.row_factory = sqlite3.Row
	cursor.execute("SELECT id FROM fys WHERE id=?", (id,))
	row = cursor.fetchone()
	if not row:
		return jsonify({"error": "Invalid id"}), 400
	account = request.args.get("account")
	if not account:
		cursor.execute(f"""
			SELECT ac_debited AS account FROM journal_{row["id"]}
			UNION SELECT ac_credited AS account FROM journal_{row["id"]}
		""")
		rows = cursor.fetchall()
		rows = [dict(row) for row in rows]
		ledger_q = request.args.get("ledger_q")
		if ledger_q:
			vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
			tfidf_matrix = vectorizer.fit_transform([row["account"].lower() for row in rows])
			query_vec = vectorizer.transform([ledger_q.strip().lower()])
			sim_scores = cosine_similarity(query_vec, tfidf_matrix).flatten()
			rows = [rows[i] for i in sim_scores.argsort()[::-1] if sim_scores[i] >= 0.3]
		return jsonify(rows), 200
	balance = 0
	cursor.execute(f"SELECT id,date,ac_credited AS account,amount FROM journal_{row["id"]} WHERE ac_debited=?", (account,))
	debit_side = cursor.fetchall()
	debit_total = 0
	if debit_side:
		debit_side = [dict(row) for row in debit_side]
		debit_total = sum([row["amount"] for row in debit_side])
		balance += debit_total
	cursor.execute(f"SELECT id,date,ac_debited AS account,amount FROM journal_{row["id"]} WHERE ac_credited=?", (account,))
	credit_side = cursor.fetchall()
	credit_total = 0
	if credit_side:
		credit_side = [dict(row) for row in credit_side]
		credit_total = sum([row["amount"] for row in credit_side])
		balance -= credit_total
	if not debit_side and not credit_side:
		return jsonify({"error": "invalid account"}), 400
	balance_side = None
	if balance > 0:
		balance_side = "credit_side"
	if balance < 0:
		balance_side = "debit_side"
	total = 0
	if debit_total and credit_total:
		total = debit_total if debit_total > credit_total else credit_total
	if not debit_total:
		total = credit_total
	if not credit_total:
		total = debit_total
	return jsonify({
		"debit_side": debit_side,
		"credit_side": credit_side,
		"balance_side": balance_side,
		"balance": abs(balance),
		"total": total
	}), 200

if __name__ == "__main__":
	app.run()