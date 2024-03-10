import os
import numpy as np
from PIL import Image, ImageDraw
from modules import shared, paths, devices, modelloader, processing, processing_class, face_restoration


class YoLoResult:
    """Class face result"""
    def __init__(self, score: float, box: list[int], mask: Image.Image = None, size: float = 0):
        self.score = score
        self.box = box
        self.mask = mask
        self.size = size


class FaceRestorerYolo(face_restoration.FaceRestoration):
    def name(self):
        return "Face HiRes"

    def __init__(self):
        self.model = None
        self.model_dir = os.path.join(paths.models_path, 'yolo')
        self.model_name = 'yolov8n-face.pt'
        self.model_url = 'https://github.com/akanametov/yolov8-face/releases/download/v0.0.0/yolov8n-face.pt'

    def predict(
            self,
            image: Image.Image,
            offload: bool = False,
            conf: float = 0.5,
            iou: float = 0.5,
            imgsz: int = 640,
            half: bool = True,
            device = 'cuda',
            n: int = 5,
            augment: bool = True,
            agnostic: bool = False,
            retina: bool = False,
            mask: bool = True,
        ) -> list[YoLoResult]:

        self.model.to(devices.device)
        predictions = self.model.predict(
            source=[image],
            stream=False,
            verbose=False,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            half=half,
            device=device,
            max_det=n,
            augment=augment,
            agnostic_nms=agnostic,
            retina_masks=retina,
        )
        if offload:
            self.model.to('cpu')
        result = []
        for prediction in predictions:
            boxes = prediction.boxes.xyxy.detach().int().cpu().numpy() if prediction.boxes is not None else []
            scores = prediction.boxes.conf.detach().float().cpu().numpy() if prediction.boxes is not None else []
            for score, box in zip(scores, boxes):
                box = box.tolist()
                mask_image = None
                size = (box[2] - box[0]) * (box[3] - box[1]) / (image.width * image.height)
                if mask:
                    mask_image = image.copy()
                    mask_image = Image.new('L', image.size, 0)
                    draw = ImageDraw.Draw(mask_image)
                    draw.rectangle(box, fill="white", outline=None, width=0)
                result.append(YoLoResult(score=score, box=box, mask=mask_image, size=size))
        return result

    def load(self):
        if self.model is None:
            model_files = modelloader.load_models(model_path=self.model_dir, model_url=self.model_url, download_name=self.model_name)
            for f in model_files:
                if self.model_name in f:
                    shared.log.info(f'Loading: type=FaceHires model={f}')
                    from ultralytics import YOLO # pylint: disable=import-outside-toplevel
                    self.model = YOLO(f)

    def restore(self, np_image, p: processing.StableDiffusionProcessing = None):
        if np_image is None or hasattr(p, 'facehires'):
            return np_image
        self.load()
        if self.model is None:
            shared.log.error(f"Model load: type=FaceHires model={self.model_name} dir={self.model_dir} url={self.model_url}")
            return np_image
        image = Image.fromarray(np_image)
        faces = self.predict(image, mask=True, device=devices.device, offload=shared.opts.face_restoration_unload)
        if len(faces) == 0:
            return np_image

        # create backups
        orig_apply_overlay = shared.opts.mask_apply_overlay
        orig_p = p.__dict__.copy()
        orig_cls = p.__class__

        pp = None
        p.facehires = True # set flag to avoid recursion
        shared.opts.data['mask_apply_overlay'] = True
        p = processing_class.switch_class(p, processing.StableDiffusionProcessingImg2Img)

        for face in faces:
            if face.mask is None:
                continue
            if face.size < 0.0002 or face.size > 0.8:
                shared.log.debug(f'Face HiRes skip: {face.__dict__}')
                continue
            p.init_images = [image]
            p.image_mask = [face.mask]
            p.inpaint_full_res = True
            p.inpainting_mask_invert = 0
            p.inpainting_fill = 1 # no fill
            p.denoising_strength = orig_p.get('denoising_strength', 0.3)
            # TODO facehires expose as tunable
            p.mask_blur = 10
            p.inpaint_full_res_padding = 15
            p.restore_faces = True
            shared.log.debug(f'Face HiRes: {face.__dict__} strength={p.denoising_strength} blur={p.mask_blur} padding={p.inpaint_full_res_padding}')
            pp = processing.process_images_inner(p)
            p.overlay_images = None # skip applying overlay twice
            if pp is not None and pp.images is not None and len(pp.images) > 0:
                image = pp.images[0]

        # restore pipeline
        p = processing_class.switch_class(p, orig_cls, orig_p)
        shared.opts.data['mask_apply_overlay'] = orig_apply_overlay
        if pp is not None and pp.images is not None and len(pp.images) > 0:
            image = pp.images[0]
            np_image = np.array(image)
        return np_image


yolo = FaceRestorerYolo()
shared.face_restorers.append(yolo)
