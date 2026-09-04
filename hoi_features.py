"""안전한 ResNet SafeTensors로 HOI 사람/물체/합집합 crop 특징을 만든다."""
from __future__ import annotations
import io
from pathlib import Path
import torch
from PIL import Image
from torchvision.transforms import v2
from transformers import ResNetModel

_transform = v2.Compose([v2.Resize((224,224)), v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
                         v2.Normalize(mean=(.485,.456,.406), std=(.229,.224,.225))])

def _crop(image: Image.Image, box: list[float]) -> torch.Tensor:
    x1,y1,x2,y2=map(int,box); return _transform(image.crop((x1,y1,max(x1+1,x2),max(y1+1,y2))).convert('RGB'))

class HOIFeaturizer:
    def __init__(self, model_dir: str|Path='data/models/resnet50'):
        self.model=ResNetModel.from_pretrained(str(model_dir),local_files_only=True).eval()
    def 크기(self, image_bytes: bytes) -> tuple[int, int]:
        """원본 (너비, 높이). 기하 대조군이 상자를 정규화하는 데 쓴다."""
        return Image.open(io.BytesIO(image_bytes)).size

    @torch.inference_mode()
    def pair(self, image_bytes: bytes, human: list[float], obj: list[float]) -> torch.Tensor:
        image=Image.open(io.BytesIO(image_bytes)); union=[min(human[0],obj[0]),min(human[1],obj[1]),max(human[2],obj[2]),max(human[3],obj[3])]
        crops=torch.stack([_crop(image,human),_crop(image,obj),_crop(image,union)])
        visual=self.model(pixel_values=crops).pooler_output.flatten(1)
        w,h=image.size; geo=torch.tensor([[x/w,y/h,(x2-x)/w,(y2-y)/h] for x,y,x2,y2 in (human,obj)],dtype=torch.float32).flatten()
        return torch.cat([visual.flatten(),geo])
