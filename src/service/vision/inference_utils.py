import os
import pathlib
import logging
import warnings
from contextlib import contextmanager

warnings.filterwarnings('ignore')

import cv2
import numpy as np
from fastai.vision.all import load_learner, PILImage
from ultralytics import YOLO

from conf.config import Config

CONFIG = Config().config
base_logger = logging.getLogger(CONFIG['logs']['api_logger']['name'])
extraction_logger = logging.getLogger(CONFIG['logs']['extraction_request_logger']['name'])

# Minimum YOLO confidence for a digit detection to be kept
DIGIT_CONFIDENCE_THRESHOLD = 0.3
# IoU above which two digit boxes are treated as duplicates
DIGIT_IOU_THRESHOLD = 0.3


@contextmanager
def _posix_paths_on_windows():
    """
    The FastAI learners were pickled on Linux/Mac and contain PosixPath objects,
    which cannot be instantiated on Windows. Map them to WindowsPath while loading.
    """
    if os.name != 'nt':
        yield
        return
    posix_path = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath
    try:
        yield
    finally:
        pathlib.PosixPath = posix_path


def _load_fastai_learner(model_path):
    base_logger.debug("Model path: %s", model_path)
    with _posix_paths_on_windows():
        return load_learner(model_path)


def load_bfm_classification(model_path=None):
    """Load the Bulk Flow Meter image quality (good/bad) FastAI classifier."""
    return _load_fastai_learner(model_path or CONFIG['models']['bfm_classification'])


def load_individual_numbers_model(model_path=None):
    """Load the YOLO oriented-bounding-box digit detector."""
    return YOLO(model_path or CONFIG['models']['individual_numbers'])


def load_color_classification_model(model_path=None):
    """Load the last-digit color (black/red) FastAI classifier."""
    return _load_fastai_learner(model_path or CONFIG['models']['color_classification'])


def _predict(model, img):
    # no_bar() stops fastai from writing a progress bar to the logs on every prediction
    with model.no_bar():
        pred_class, pred_idx, probs = model.predict(img)
    return {
        'prediction': str(pred_class),
        'confidence': float(probs[pred_idx]),
        'all_probs': [float(p) for p in probs]
    }


def classify_bfm_image(image_rgb: np.ndarray, model):
    """
    Classify a Bulk Flow Meter image as good or bad.

    Args:
        image_rgb: RGB image as a numpy array
        model: Loaded BFM classification learner

    Returns:
        Dictionary with 'prediction', 'confidence' and 'all_probs'
    """
    return _predict(model, PILImage.create(image_rgb))


def classify_color_image(image_bgr: np.ndarray, model):
    """Classify a (BGR) digit crop as black or red."""
    return _predict(model, PILImage.create(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)))


def enhance_image(image):
    """
    Enhance the image to improve readability for image while preserving color
    """
    enhance_config = CONFIG['image_enhancement']

    # Convert to HSV color space to separate brightness from color
    h, s, v = cv2.split(cv2.cvtColor(image, cv2.COLOR_BGR2HSV))

    # Apply unsharp masking for sharpening to the value channel
    gaussian = cv2.GaussianBlur(v, (0, 0), 3.0)
    sharpened_v = cv2.addWeighted(v, enhance_config['sharpening_alpha'], gaussian, enhance_config['sharpening_beta'], 0)

    # Increase contrast in the value channel
    clahe = cv2.createCLAHE(
        clipLimit=enhance_config['clahe_clip_limit'],
        tileGridSize=tuple(enhance_config['clahe_tile_grid_size'])
    )
    enhanced_v = clahe.apply(sharpened_v)

    enhanced = cv2.cvtColor(cv2.merge([h, s, enhanced_v]), cv2.COLOR_HSV2BGR)

    # Apply color boost to make digits stand out more
    return cv2.convertScaleAbs(enhanced, alpha=enhance_config['color_boost_alpha'], beta=enhance_config['color_boost_beta'])


def calculate_iou(box1, box2):
    """
    Intersection over Union between two convex 4-point polygons (oriented boxes).
    """
    poly1 = box1.astype(np.float32)
    poly2 = box2.astype(np.float32)
    intersection, _ = cv2.intersectConvexConvex(poly1, poly2)
    union = cv2.contourArea(poly1) + cv2.contourArea(poly2) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def remove_overlapping_boxes(boxes, classes, confidences, iou_threshold=0.5):
    """
    Non-maximum suppression: among overlapping boxes keep only the most confident one.
    """
    box_data = sorted(zip(boxes, classes, confidences), key=lambda x: x[2], reverse=True)

    kept = []
    while box_data:
        current = box_data.pop(0)
        kept.append(current)
        box_data = [other for other in box_data if calculate_iou(current[0], other[0]) < iou_threshold]

    filtered_boxes, filtered_classes, filtered_confidences = (list(x) for x in zip(*kept))
    return filtered_boxes, filtered_classes, filtered_confidences


def direct_recognize_meter_reading(image_bgr: np.ndarray, individual_numbers_model):
    """
    Detect individual digits and read them left to right.

    Args:
        image_bgr: BGR image as a numpy array
        individual_numbers_model: Loaded YOLO digit detector

    Returns:
        (meter_reading, sorted_boxes, sorted_classes); meter_reading is None if no digits were found
    """
    digit_results = individual_numbers_model(enhance_image(image_bgr), verbose=False)

    digit_boxes = []
    digit_classes = []
    digit_confidences = []

    for result in digit_results:
        if result.obb is None:
            continue
        polygons = result.obb.xyxyxyxy.cpu().numpy().astype(np.int32)
        class_ids = result.obb.cls.int().tolist()
        confidences = result.obb.conf.tolist()
        for points, class_id, confidence in zip(polygons, class_ids, confidences):
            if confidence > DIGIT_CONFIDENCE_THRESHOLD:
                digit_boxes.append(points.reshape(-1, 2))
                digit_classes.append(class_id)
                digit_confidences.append(confidence)

    extraction_logger.debug("Original digit results: %s", digit_classes)

    if not digit_boxes:
        return None, [], []

    digit_boxes, digit_classes, _ = remove_overlapping_boxes(
        digit_boxes, digit_classes, digit_confidences, iou_threshold=DIGIT_IOU_THRESHOLD
    )

    # Sort left to right by each box's leftmost x-coordinate
    sorted_pairs = sorted(zip(digit_boxes, digit_classes), key=lambda pair: pair[0][:, 0].min())
    sorted_boxes = [box for box, _ in sorted_pairs]
    sorted_classes = [cls for _, cls in sorted_pairs]

    meter_reading = ''.join(str(cls) for cls in sorted_classes)
    return meter_reading, sorted_boxes, sorted_classes


def extract_digit_image(image, box):
    """Crop a digit's polygon out of the image, masking everything outside it."""
    # Oriented boxes can poke slightly outside the image; negative indices would wrap around
    box = np.clip(box, 0, [image.shape[1] - 1, image.shape[0] - 1]).astype(np.int32)
    x, y, w, h = cv2.boundingRect(box)
    cropped = image[y:y+h, x:x+w].copy()

    mask = np.zeros(cropped.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [box - np.array([x, y])], 255)

    return cv2.bitwise_and(cropped, cropped, mask=mask)
