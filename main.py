import requests
import inspect
from datetime import date
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Float, Date
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel, model_validator, Field, field_validator

# --- Configuração do Banco de Dados (SQLite com SQLAlchemy) ---
DATABASE_URL = "sqlite:///./DB/mangadb.sqlite3"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Modelo da Tabela de Mangás ---
class Manga(Base):
    __tablename__ = 'mangas'
    id = Column(Integer, primary_key=True, index=True)
    id_api = Column(Integer, unique=True, index=True)
    name = Column(String, index=True)
    cover_url = Column(String)
    chapters = Column(Integer, nullable=True)
    chapters_read = Column(Integer, nullable=False, default=0)
    type = Column(String, nullable=True)
    status = Column(String, nullable=True)
    score = Column(Float, nullable=True)
    rank = Column(Integer, nullable=True)
    popularity = Column(Integer, nullable=True)
    start_date = Column(Date, nullable=True)
    finish_date = Column(Date, nullable=True)

# Cria a tabela no banco de dados, se ela não existir
Base.metadata.create_all(bind=engine)

# --- Modelos Pydantic para Validação de Dados ---

# Modelo para a CRIAÇÃO de um novo mangá
class MangaCreate(BaseModel):
    id_api: int
    name: str
    cover_url: str
    chapters: int | None = Field(default=None, ge=0)
    type: str | None
    status: str | None
    score: float | None
    rank: int | None
    popularity: int | None
    start_date: date | None = None
    finish_date: date | None = None
    chapters_read: int = Field(default=0, ge=0)
    
    # Validador para garantir que chapters nulo vire 0
    @field_validator("chapters", mode="before")
    def empty_str_to_none(cls, v):
        if v is None:
            return 0
        return v

    @model_validator(mode='after')
    def check_chapters(self) -> 'MangaCreate':
        if self.chapters is not None and self.chapters_read is not None:
            if self.chapters_read > self.chapters:
                raise ValueError('Capítulos lidos não pode ser maior que o total.')
        return self

# Helper para usar modelos Pydantic com formulários HTML
def as_form(cls: type[BaseModel]):
    new_parameters = [
        inspect.Parameter(
            field.alias or field_name,
            inspect.Parameter.POSITIONAL_ONLY,
            default=Form(field.default if field.default is not None else ...),
        )
        for field_name, field in cls.model_fields.items()
    ]
    async def as_form_func(**data):
        return cls(**data)
    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig
    return as_form_func

# Modelo para o formulário de ATUALIZAÇÃO
@as_form
class MangaUpdateForm(BaseModel):
    chapters: int = Field(ge=0)
    chapters_read: int = Field(ge=0)

    @model_validator(mode='after')
    def check_chapters_read_not_greater_than_total(self) -> 'MangaUpdateForm':
        if self.chapters is not None and self.chapters_read is not None:
            if self.chapters_read > self.chapters:
                raise ValueError('Capítulos lidos não pode ser maior que o total.')
        return self

# --- Configuração do FastAPI ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
JIKAN_API_URL = "https://api.jikan.moe/v4/manga"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Rotas da Aplicação (Endpoints) ---

# Rota Principal
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
    mangas_cadastrados = db.query(Manga).order_by(Manga.name).all()
    return templates.TemplateResponse("index.html", {"request": request, "mangas": mangas_cadastrados})

# Rota da API para buscar mangás na Jikan
@app.post("/api/buscar-manga", summary="Busca uma lista de mangás na API externa")
def api_buscar_manga(manga_name: str = Form(...)):
    search_response = requests.get(f"{JIKAN_API_URL}?q={manga_name}&limit=15")
    if search_response.status_code != 200 or not search_response.json().get('data'):
        raise HTTPException(status_code=404, detail="Nenhum mangá encontrado com esse nome.")
    return JSONResponse(content=search_response.json()['data'])

# Rota da API para buscar detalhes de um mangá específico
@app.get("/api/manga/{manga_id}", summary="Busca os detalhes de um mangá pelo seu ID")
def api_get_manga_details(manga_id: int):
    full_response = requests.get(f"{JIKAN_API_URL}/{manga_id}/full")
    if full_response.status_code != 200 or not full_response.json().get('data'):
        raise HTTPException(status_code=404, detail="Não foi possível obter os detalhes completos do mangá.")
    return JSONResponse(content=full_response.json().get('data'))

# Rota da API para salvar um novo mangá no banco
@app.post("/api/salvar-manga", summary="Salva um novo mangá na coleção")
def api_salvar_manga(manga_data: MangaCreate, db: Session = Depends(get_db)):
    manga_existente = db.query(Manga).filter(Manga.id_api == manga_data.id_api).first()
    if manga_existente:
        raise HTTPException(status_code=409, detail="Este mangá já está cadastrado.")
    
    novo_manga = Manga(**manga_data.model_dump())
    db.add(novo_manga)
    db.commit()
    return {"status": "sucesso", "message": f"Mangá '{novo_manga.name}' salvo!"}

# Rota para renderizar a página de edição de um mangá
@app.get("/manga/edit/{manga_id}", response_class=HTMLResponse)
def get_edit_manga_page(request: Request, manga_id: int, db: Session = Depends(get_db)):
    manga = db.query(Manga).filter(Manga.id == manga_id).first()
    if not manga:
        raise HTTPException(status_code=404, detail="Mangá não encontrado no seu banco de dados.")
    return templates.TemplateResponse("edit_manga.html", {"request": request, "manga": manga})

# Rota para processar a atualização de um mangá
@app.post("/manga/update/{manga_id}", summary="Atualiza os dados de um mangá existente")
def update_manga(manga_id: int, db: Session = Depends(get_db), form_data: MangaUpdateForm = Depends(MangaUpdateForm)):
    """
    Atualiza APENAS o número de capítulos totais e lidos de um mangá.
    """
    manga = db.query(Manga).filter(Manga.id == manga_id).first()
    if not manga:
        raise HTTPException(status_code=404, detail="Mangá não encontrado.")

    # Atualiza apenas os dois campos permitidos
    manga.chapters = form_data.chapters
    manga.chapters_read = form_data.chapters_read
    
    db.commit()

    return RedirectResponse(url="/", status_code=303)

# Rota para deletar um mangá
@app.post("/manga/delete/{manga_id}", summary="Deleta um mangá da coleção")
def delete_manga(manga_id: int, db: Session = Depends(get_db)):
    manga = db.query(Manga).filter(Manga.id == manga_id).first()
    if manga:
        db.delete(manga)
        db.commit()
    return RedirectResponse(url="/", status_code=303)