from flask import Flask, Response, request, session
import uuid
import json
from dotenv import load_dotenv
import os
import threading
import time
from enum import Enum
from typing import TypedDict

app = Flask(__name__)
load_dotenv()

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

DeliveryStatus = Enum('DeliveryStatus', 'undefined submitted registered delivered')


class Message(TypedDict):
    id: str
    status: str
    user_id: str
    registered_at: int
    text: str
    submission_id: str

    # def __iter__(self):
    #     yield 'id', self.id
    #     yield 'status', self.status
    #     yield 'userId', self.user_id
    #     yield 'registeredAt', self.registered_at
    #     yield 'text', self.text
    #     yield 'submissionId', self.submission_id

class MessageLog:
    def __init__(self):
        self._messages: list[Message] = []

    def _index(self, message_id: str) -> int | None:
        for i, m in enumerate(self._messages):
            if m['id'] == message_id:
                return i
        return None
    
    def after(self, message_id: str) -> list[Message]:
        index = self._index(message_id)
        if index is None: return []
        return self._messages[index:]
    
    def append(self, message: Message):
        self._messages.append(message)

    def ends_with(self, message_id: str) -> bool:
        return self._messages and self._messages[-1]['id'] == message_id
    
    def empty(self) -> bool:
        return not self._messages
    
    def all(self) -> list[Message]:
        return self._messages
    
message_log = MessageLog()

last_sent : dict[int, str] = {} # key = thread id, value = the id of the last message sent in the response
lock = threading.Condition()

@app.route("/sse")
def render():
    if 'userId' not in session:
        session['user_id'] = str(uuid.uuid4())
    with open('html/index.html') as f:
        return f.read()


@app.post("/sse/post")
def post():
    message = Message(**request.json)
    print(message)
    # message = request.json
    message['id'] = str(uuid.uuid4())
    message['status'] = DeliveryStatus.registered.name
    message['user_id'] = session['user_id']
    message['registered_at'] = time.time()
    message_log.append(message)

    lock.acquire()
    lock.notify_all()
    lock.release()

    return message


def block_until_new_messages(last_seen_id: str, timeout: float):
    has_new_messages = lambda: (
        not message_log.empty()
        and not message_log.ends_with(last_seen_id)
    )

    timed_out = False
    while not timed_out and not has_new_messages():
        lock.acquire()
        timed_out = not lock.wait(timeout)
        lock.release()
    return timed_out


def wait_for_event(thread_id):
    last_seen_id = last_sent[thread_id]
    timed_out = block_until_new_messages(last_seen_id, timeout=20)
    if timed_out:
        return f':\n\n'
    new_messages = message_log.after(last_seen_id)
    if not new_messages:
        new_messages = message_log.all()
    last_sent[thread_id] = new_messages[-1]['id']
    return serialize(new_messages)


def serialize(messages: list):
    items = []
    for _, msg in enumerate(messages):
        items.append(f'id: {msg['id']}\n'
                     f'data: {json.dumps(msg)}\n\n')
    return ''.join(items)


def cleanup_threads():
    to_delete = []
    all_ids = [t.ident for t in threading.enumerate()]
    for id in last_sent.keys():
        if id not in all_ids:
            to_delete.append(id)
    for id in to_delete:
        del last_sent[id]


@app.route('/sse/events')
def events():
    last_id = request.headers.get('Last-Event-Id', None)
    user_id = session.get('user_id', None)
    if user_id is None:
        return 401, 'no user_id in session'
    def eventStream():
        last_sent[threading.get_ident()] = last_id
        while True:
            cleanup_threads()
            yield wait_for_event(threading.get_ident())

    return Response(eventStream(), mimetype="text/event-stream")
