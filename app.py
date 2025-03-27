from flask import Flask, Response, request, session
import uuid
import json
from dotenv import load_dotenv
import os
import threading

app = Flask(__name__)
load_dotenv()

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

messages = []
queues = {}
queue_condition = threading.Condition()

@app.route("/sse")
def render():
    if 'userId' not in session:
        session['userId'] = str(uuid.uuid4())
    with open('html/index.html') as f:
        return f.read()

@app.post("/sse/post")
def post():
    message = request.json
    message['id'] = str(uuid.uuid4())
    message['status'] = 'registered'
    message['userId'] = session['userId']
    messages.append(message)

    for threadId in queues.keys():
       queues[threadId].append(message)

    print(queues)
    print(f'{session['userId']}: appended message: {message['text']}')
    queue_condition.acquire()
    print(f'{session['userId']}: notify_all()')
    queue_condition.notify_all()
    queue_condition.release()
    return message

def serialize(queue: list):
    items = []
    for index, msg in enumerate(queue):
        items.append(f'id: {msg['id']}\n'
                     f'data: {json.dumps(msg)}\n\n')
    return ''.join(items)

def wait_user(threadId):
    keepalive = False
    while not keepalive and len(queues[threadId]) == 0:
        print(f'{threadId}: will acquire')
        queue_condition.acquire()
        print(f'{threadId}: will wait')
        keepalive = not queue_condition.wait(20)
        if not keepalive:
            print(f'{threadId}: wait ended due to a notify')
        else:
            print(f'{threadId}: wait ended due to a keepalive')
    data_to_send = f':\n\n' if keepalive else serialize(queues[threadId])
    if not keepalive:
        print(f'queues[{threadId}] before clear: {queues[threadId]}')
        queues[threadId].clear()
    return data_to_send

streams = []

@app.route('/sse/events')
def events():
    lastid = request.headers.get('Last-Event-Id', None)
    request.stream
    userId = session.get('userId', None)
    if userId is None:
        return 401, 'session has no userId'
    if threading.get_ident() not in queues:
        queues[threading.get_ident()] = []
    def eventStream():
        last_seen_index = next((i for i, m in enumerate(messages) if m['id'] != lastid), None)
        if last_seen_index is not None:
            queues[threading.get_ident()] += messages[last_seen_index:]
        global streams
        streams.append(userId)
        print(f'{len(streams)} streams: {", ".join(streams)}')
        while True:
            yield wait_user(threading.get_ident())

    return Response(eventStream(), mimetype="text/event-stream")
