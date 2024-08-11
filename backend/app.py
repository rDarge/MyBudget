import os
from typing import Annotated, List
from fastapi import Depends, FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import uvicorn

from backend.csv import parse_csv
from backend.messages import (
    AccountData,
    GetTransactionsResponse,
    PostAccountRequest,
    TransactionData,
)
from database.models import Account, Transaction, TransactionFile

app = FastAPI()

origins = ["http://localhost:8000", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Alive"}


default_engine = None


def get_default_engine():
    if default_engine:
        return default_engine
    conn_string = os.environ.get("SQLALCHEMY_CONNECTION_STRING")
    engine = create_engine(conn_string, future=True)
    return Session(engine)


async def session():
    return get_default_engine()


SessionDep = Annotated[Session, Depends(session)]


@app.post("/account", response_model=AccountData)
async def post_account(session: SessionDep, request: PostAccountRequest):
    """Testing: curl -H "Content-Type: application/json" -d "{\"name\":\"test\"}" http://localhost:8000/account"""
    with session.begin():
        new_account = Account(name=request.name)
        session.add(new_account)
        session.commit()

    return AccountData.model_validate(new_account, from_attributes=True)


@app.get("/accounts", response_model=List[AccountData])
async def get_accounts(session: SessionDep):
    """Testing: curl localhost:8000/accounts"""
    with session.begin():
        accounts: List[Account] = session.query(Account).all()
        convert_to_message = lambda account: AccountData.model_validate(
            account, from_attributes=True
        )
        return map(convert_to_message, accounts)


@app.post("/account/{account_id}/import")
async def import_csv(account_id: int, uploadFile: UploadFile, session: SessionDep):
    """Testing: curl -L -F "uploadFile=@test_data/sensitive/sample_transactions_checking.CSV" http://localhost:8000/account/1/import"""
    with uploadFile.file as binaryFile:

        # Persist file for reference.
        with session.begin():
            # TODO: Short-circuit if the file already exists (unique constraint maybe?)
            file = TransactionFile(
                filename=uploadFile.filename,
                data=binaryFile.read(),
            )
            session.add(file)
            session.commit()

        # Secondarily, parse file
        binaryFile.seek(0)
        with session.begin():
            transactions = parse_csv(binaryFile)
            for transaction in transactions:
                # TODO: Check to see if the transactions already exist!
                transaction.account_id = account_id
                session.add(transaction)
            session.commit()

        # TODO: Return a summary of the operations performed (# added, # skipped)
        return {"description": transactions[0].description, "total": len(transactions)}


@app.get("/account/{account_id}/transactions", response_model=GetTransactionsResponse)
async def get_transactions(
    session: SessionDep,
    account_id: int,
    page: int = 0,
    per_page: int = 20,
):

    # Persist file for reference.
    with session.begin():
        transactions = (
            session.query(Transaction)
            .filter(Transaction.account_id == account_id)
            .order_by(Transaction.post_date.desc())
            .offset(page * per_page)
            .limit(per_page)
            .all()
        )

    transactionData = [
        TransactionData.model_validate(transaction, from_attributes=True)
        for transaction in transactions
    ]
    return GetTransactionsResponse(
        transactions=transactionData, page=page, per_page=per_page
    )


def start():
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
