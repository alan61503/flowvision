import logging
import traceback
from http import HTTPStatus
from datetime import datetime
from uuid import uuid4, UUID
from io import BytesIO

import cv2
import numpy as np
import requests
from fastapi import BackgroundTasks
from PIL import Image

from conf.config import Config
from models.models import Error, Status, ReadingExtractionRequest, ReadingExtractionResponse, ReadingExtractionResult, ReadingExtractionResultData, ResponseCode, FeedbackRequest, FeedbackResponseStatus, FeedbackResponse, FeedbackStatus, BaseResponse
from service.api.metadata_service import MetadataStore
from service.vision.inference_utils import (
    load_bfm_classification,
    load_individual_numbers_model,
    load_color_classification_model,
    classify_bfm_image,
    direct_recognize_meter_reading,
    classify_color_image,
    extract_digit_image
)


class ImageService:
    def __init__(self, config: Config):
        self.base_logger = logging.getLogger(config.find("logs.api_logger.name"))
        self.feedback_logger = logging.getLogger(config.find("logs.feedback_request_logger.name"))
        self.extraction_logger = logging.getLogger(config.find("logs.extraction_request_logger.name"))
        self.download_timeout = config.find("image_download_timeout", 30)

        self.metadata_store = MetadataStore(config=config)

        self.base_logger.info("Loading models...")
        self.bfm_classification_model = load_bfm_classification()
        self.individual_numbers_model = load_individual_numbers_model()
        self.color_classification_model = load_color_classification_model()

    def download_image(self, image_url) -> np.ndarray:
        """Download an image and return it as an RGB numpy array."""
        response = requests.get(image_url, timeout=self.download_timeout)
        response.raise_for_status()
        return np.array(Image.open(BytesIO(response.content)).convert("RGB"))

    def extract_reading(self, request: ReadingExtractionRequest, background_tasks: BackgroundTasks) -> ReadingExtractionResponse:
        request.id = request.id if request.id else uuid4()
        request.ts = request.ts if request.ts else datetime.now()
        background_tasks.add_task(self.metadata_store.store_request, request)

        try:
            start_time = datetime.now()
            self.extraction_logger.info(request.model_dump_json())
            image_rgb = self.download_image(request.imageURL)

            quality_result = classify_bfm_image(image_rgb, model=self.bfm_classification_model)
            quality_status = quality_result['prediction'].lower()
            quality_confidence = quality_result['confidence']

            color_result = {"prediction": "unknown", "confidence": 0.0}

            # Only attempt a reading if the image passes the quality gate
            if quality_status != 'good':
                meter_reading_status = Status.UNCLEAR
                meter_reading = "Image quality too poor for recognition"
            else:
                image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
                meter_reading, sorted_boxes, _ = direct_recognize_meter_reading(image_bgr, self.individual_numbers_model)

                if meter_reading is None:
                    meter_reading_status = Status.UNCLEAR
                    meter_reading = "No digits detected in the image"
                else:
                    meter_reading_status = Status.SUCCESS
                    last_digit_image = extract_digit_image(image_bgr, sorted_boxes[-1])
                    color_result = classify_color_image(last_digit_image, model=self.color_classification_model)

            processing_time = (datetime.now() - start_time).total_seconds()

            response = ReadingExtractionResponse(
                id=request.id,
                ts=datetime.now(),
                responseCode=ResponseCode.OK,
                statusCode=HTTPStatus.OK.value,
                result=ReadingExtractionResult(
                    status=meter_reading_status,
                    correlationId=uuid4(),
                    data=ReadingExtractionResultData(
                        meterReading=meter_reading,
                        processingTime=processing_time,
                        qualityStatus=quality_status,
                        qualityConfidence=quality_confidence,
                        lastDigitColor=color_result['prediction'].lower(),
                        colorConfidence=color_result['confidence']
                    )
                )
            )
            background_tasks.add_task(self.metadata_store.store_response, response)
        except Exception as e:
            response = self.handle_exception(error=e, id=request.id)

        self.extraction_logger.info(response.model_dump_json())
        return response

    def log_feedback(self, request: FeedbackRequest, background_tasks: BackgroundTasks):
        request.id = request.id if request.id else uuid4()
        request.ts = request.ts if request.ts else datetime.now()
        background_tasks.add_task(self.metadata_store.store_feedback, request)

        self.feedback_logger.info(request.model_dump_json())
        response = FeedbackResponse(
            id=request.id,
            ts=datetime.now(),
            responseCode=ResponseCode.OK,
            statusCode=HTTPStatus.OK.value,
            result=FeedbackStatus(status=FeedbackResponseStatus.SUBMITTED)
        )
        self.feedback_logger.info(response.model_dump_json())
        return response

    def handle_exception(self, error: Exception, id: UUID):
        self.base_logger.error("\nError type: %s\nRequest id: %s\nTrace: %s", type(error).__name__, id, traceback.format_exc())

        response = BaseResponse(
            id=id,
            ts=datetime.now(),
            responseCode=ResponseCode.ERROR,
            statusCode=HTTPStatus.INTERNAL_SERVER_ERROR.value,
            error=Error(errorCode=HTTPStatus.INTERNAL_SERVER_ERROR.value, errorMsg=str(error))
        )
        self.base_logger.error(response.model_dump_json())
        return response
