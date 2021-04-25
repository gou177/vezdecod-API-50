from enum import Enum
from typing import Dict, List, Optional
from fastapi import FastAPI
import secrets
from fastapi.exceptions import HTTPException
from fastapi.param_functions import Depends, Query
from pydantic import BaseModel, Field
from pydantic.class_validators import validator
import random
import uvicorn
import threading
import time
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ImgStatus(str, Enum):
    CLOSED = "CLOSED"
    TEMP_OPEN = "TEMP_OPEN"
    OPEN = "OPEN"
    CLOSING = "CLOSING"


class Item(BaseModel):
    photoId: int
    status: ImgStatus = Field(
        ImgStatus.CLOSING,
        description="CLOSING - будет закрыто на след. ходу; CLOSED - невиден; OPEN - виден; TEMP_OPEN - временно виден, может быть закрыт",
    )


class Game(BaseModel):
    token: str = Field(default_factory=secrets.token_urlsafe)
    items: List[List[Item]] = []
    ended: bool = False
    started_at: float = Field(default_factory=time.time)
    score: int = 0

    @validator("items", pre=True, always=True)
    def createItems(cls, v):
        if v:
            return v
        photos = list(range(8)) * 2
        random.shuffle(photos)

        return [
            [Item(photoId=p) for p in photos[i * 4 : (i + 1) * 4]] for i in range(4)
        ]


class GameWithExtras(Game):
    _token2game: Dict[str, "GameWithExtras"] = {}
    ended_event: threading.Event = Field(default_factory=threading.Event)
    end_timer: Optional[threading.Timer] = None

    def store(self):
        self._token2game[self.token] = self

    def end(self):
        if not self.ended:
            self.ended = True
            self.ended_event.set()
            self._token2game.pop(self.token)

    def start(self):
        self.end_timer = threading.Timer(65, self.end)
        self.end_timer.start()

    class Config:
        arbitrary_types_allowed = True


class Error(BaseModel):
    message: str


@app.post(
    "/games/create",
    response_model=Game,
    description="Создать игру",
)
def create_game():
    game = GameWithExtras()
    game.start()
    game.store()
    return game


@app.get(
    "/games/{game_token}",
    response_model=Game,
    description="Найти игру по её токену",
    responses={
        404: {"model": Error},
    },
)
def get_game_by_token(game_token: str) -> GameWithExtras:
    game = GameWithExtras._token2game.get(game_token, None)

    if game is None:
        raise HTTPException(404, {"message": "Game not found"})

    return game


@app.post(
    "/games/{game_token}/open",
    response_model=Game,
    description="Открыть картинку",
    responses={
        404: {"model": Error},
        409: {"model": Error},
    },
)
def open_game_pic(
    row: int = Query(..., ge=0, le=3),
    col: int = Query(..., ge=0, le=3),
    game: GameWithExtras = Depends(get_game_by_token),
):
    item = game.items[row][col]

    if item.status in [ImgStatus.OPEN, ImgStatus.TEMP_OPEN]:
        raise HTTPException(409, {"message": "Item already opened"})

    item.status = ImgStatus.TEMP_OPEN
    temp_opened: List[Item] = []

    for item_row in game.items:
        for item in item_row:
            if item.status == ImgStatus.TEMP_OPEN:
                temp_opened.append(item)
            if item.status == ImgStatus.CLOSING:
                item.status = ImgStatus.CLOSED

    if len(temp_opened) < 2:
        return game

    item1 = temp_opened[0]
    item2 = temp_opened[1]

    if item1.photoId == item2.photoId:
        item1.status = ImgStatus.OPEN
        item2.status = ImgStatus.OPEN

        game.score += 30
    else:
        game.score -= 10

        item1.status = ImgStatus.CLOSING
        item2.status = ImgStatus.CLOSING

    opened: List[Item] = []

    for item_row in game.items:
        for item in item_row:
            if item.status == ImgStatus.OPEN:
                opened.append(item)

    if len(opened) == 16:
        game.end()

    return game


app.mount("/", StaticFiles(directory="."))
uvicorn.run(app, host="0.0.0.0")
