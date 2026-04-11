PLUGIN_META = {
    "name": "Gesture Action Mode",
    "description": "Performs actions based on gestures of hand"
}

hand_map = {
    ('Left', 'open_palm'): 0,
    ('Left', 'peace'): 0,
    ('Left', 'three_fingers'): 0,
    ('Left', 'pinch'): 1,
    ('Left', 'point'): 1,
    ('Left', 'fist'): 1,
    ('Right', 'open_palm'): 2,
    ('Right', 'peace'): 2,
    ('Right', 'three_fingers'): 2,
    ('Right', 'pinch'): 3,
    ('Right', 'point'): 3,
    ('Right', 'fist'): 3,
}
action_gestures = {
    "open_palm",
    "peace",
    "three_fingers",
    "pinch",
    "point",
    "fist",
}
gesture_priority = {
    "pinch": 7,
    "open_palm": 6,
    "peace": 5,
    "three_fingers": 4,
    "point": 3,
    'fist': 2,
    'hover': 1,
}
pinch_threshold = 0.07
required_stable_frames = 2
cooldown_ms = 1000

#global variables
selection_queue = []
current_target = None
start_time = 0
last_added_target = None
last_confirm_time = 0
last_clear_time = 0
STABILITY = {}
COMMIT_DWELL_MS = 800


#setup for global variables
def setup(payload):
    global selection_queue, STABILITY, last_added_target, current_target

    selection_queue = []
    STABILITY = {}
    last_added_target = None
    current_target = None
    return {
        'status': 'Object queueing plugin ready',
        'available': len(payload.get("savedOperations", [])),
    }

# helper to fetch a saved operation from manual
def index_operation(frame,index):
    saved = frame.get("savedOperations", [])
    if index is None or index < 0 or index >= len(saved):
        return None
    return saved[index]

def finger_states(hand):
    return hand.get('fingerStates') or {}

def hand_label(hand):
    return hand.get('handedness') or hand.get('viewerSide') or 'Unknown'

def update_stability(target_id):
    global STABILITY

    if target_id is None:
        STABILITY = {}
        return 0
    
    next_counts = {}
    next_counts[target_id] = STABILITY.get(target_id, 0) + 1
    STABILITY = next_counts
    return STABILITY[target_id]

def count_no_thumb(hand):
    runtime_value = hand.get('fingerCountNoThumb')
    if runtime_value is not None:
        return int(runtime_value)
    states = finger_states(hand)
    return sum(
        1 for key in ('indexExtended', 'middleExtended', 'ringExtended', 'pinkyExtended')
        if states.get(key)
    )

def count_with_thumb(hand):
    runtime_value =  hand.get('fingerCountWithThumb')
    if runtime_value is not None:
        return int(runtime_value)
    states = finger_states(hand)
    return count_no_thumb(hand) + (1 if states.get('thumbExtended') else 0)

def get_active_hand(frame):
    primary = frame.get("primaryHand")
    if primary:
        return primary
    
    hands = frame.get('hands', [])
    if hands:
        return hands[0]
    
    return None
    
def active_target(point, boxes, centers):
    for box_id, box in boxes.items():
        if inside_box(point, box):
            return box_id
        
    closest_id = None
    closest_dist = None

    for box_id, center in centers.items():
        dx = point['x'] - center['x']
        dy = point['y'] - center['y']
        dist_sq = dx * dx + dy * dy

        if closest_dist is None or dist_sq < closest_dist:
            closest_dist = dist_sq
            closest_id = box_id
            
    return closest_id
    
def what_gesture(hand):
    states = finger_states(hand)
    pinch_distance = hand.get('pinchDistance', 1.0)
    no_thumb = count_no_thumb(hand)
    with_thumb = count_with_thumb(hand)

    index_up = bool(states.get('indexExtended'))
    middle_up = bool(states.get('middleExtended'))
    ring_up = bool(states.get('ringExtended'))
    pinky_up = bool(states.get('pinkyExtended'))

    if pinch_distance < pinch_threshold and index_up:
        return 'pinch', 0.97
    if no_thumb >=4 and with_thumb >= 4 and pinch_distance > 0.075:
        return 'open_palm', 0.95
    if index_up and middle_up and ring_up and not pinky_up:
        return 'three_fingers', 0.91
    if index_up and middle_up and not ring_up and not pinky_up:
        return 'peace', 0.89
    if index_up and not middle_up and not ring_up and not pinky_up:
        return 'point', 0.87
    if with_thumb <= 1 and pinch_distance >0.08:
        return 'fist', 0.84
    return 'hover', 0.55

def box_centers(frame):
    center = {}
    boxes = {}
    for box in frame.get("bayesBoxes", {}).get('boxes', []):
        center[box['id']] = {
            'x': box['x'] + box['width'] * 0.5,
            'y': box['y'] + box['height'] * 0.5,
        }
        boxes[box['id']] = box
    return center, boxes
    
def inside_box(point, box):
    return (
        box['x'] <= point['x'] <= box['x'] + box['width']
        and box['y'] <= point['y'] <= box['y'] + box['height']
    )
    
def target_operation(frame, target_id):
    operation = None

    if target_id == 'red':
        operation = index_operation(frame, 0)
    elif target_id == 'green':
        operation = index_operation(frame, 1)
    elif target_id == 'blue':
        operation = index_operation(frame, 2)

    if operation is None:
        return None
    
    return {
        'target_id': target_id,
        'operation_id': operation['id'],
        'operation_name': operation['name'],
    }

def processframeframe(frame):
    global current_target, start_time, STABILITY

    now = frame.get('timestampMs', 0)
    hand = get_active_hand(frame)

    if hand is None:
        current_target = None
        STABILITY = {}
        return {
            "label": 'No hand detected',
            "confidence": 0.0,
            "warning": ['show one hand to the webcam']
        }
    
    gesture,confidence = what_gesture(hand)
    point = hand.get('indexTip') or hand.get('palmCenter')
    if point is None:
        return {
            "label": "No point available",
            "confidence": 0.0,
            "warning": ['could not read fingers or palm']
        }

    centers, boxes = box_centers(frame)

    if not boxes:
        return {
            "label": 'No targets available',
            "confidence": 0.0,
            "warning":['no bayesBoxes were found in the camera frame']
        }
    
    target_id = active_target(point, boxes, centers)

    if target_id != current_target:
        current_target = target_id
        start_time = now
        STABILITY = {target_id: 1} if target_id is not None else {}
        stable_frames = STABILITY.get(target_id, 0)
    else:
        stable_frames = update_stability(target_id)
    
    dwell_time = now - start_time
    target_commit = (target_id is not None and dwell_time >= COMMIT_DWELL_MS and stable_frames >= required_stable_frames)
    return {
        "label": f'Target {target_id} ({gesture})',
        "confidence": confidence,
        "warning": [f'Stable frames: {stable_frames}', 
                    f'Dwell time: {dwell_time}',
                    f'committed: {target_commit}',
                    ]
    }