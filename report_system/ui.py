import json
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from report_system.application import ReportApplication
from report_system.config import Settings
from report_system.domain import Document, DocumentType


@st.cache_resource
def create_application() -> ReportApplication:
    return ReportApplication(Settings())


def run() -> None:
    st.set_page_config(page_title="Локальные технические отчёты", layout="wide")
    st.title("Локальная система технических отчётов")
    application = create_application()
    create_tab, list_tab, act_tab = st.tabs(["Создание документа", "Документы", "Акт испытаний"])

    with create_tab:
        _render_create(application)
    with list_tab:
        _render_list(application)
    with act_tab:
        _render_test_act(application)


def _render_create(application: ReportApplication) -> None:
    labels = {
        "Акт наработки": DocumentType.MANUFACTURING_ACT,
        "Протокол испытаний": DocumentType.TEST_PROTOCOL,
    }
    selected = st.selectbox("Тип документа", list(labels))
    raw_input = st.text_area("Свободное описание", height=180)
    if st.button("Разобрать", type="primary"):
        try:
            extracted = application.extract(labels[selected], raw_input)
            st.session_state["review_json"] = extracted.model_dump_json(indent=2)
            st.session_state["review_editor"] = st.session_state["review_json"]
            st.session_state.pop("confirmed_id", None)
        except Exception as error:
            st.error(f"Ошибка extraction: {error}")

    if "review_json" in st.session_state:
        reviewed = st.text_area(
            "Извлечённые данные (проверьте и отредактируйте JSON)",
            height=420,
            key="review_editor",
        )
        if st.button("Подтвердить и сохранить"):
            try:
                document = application.confirm(Document.model_validate_json(reviewed))
                st.session_state["review_json"] = document.model_dump_json(indent=2)
                st.session_state["confirmed_id"] = document.id
                st.success(f"Документ {document.id} подтверждён")
            except (ValidationError, ValueError) as error:
                st.error(f"Некорректные structured data: {error}")

    confirmed_id = st.session_state.get("confirmed_id")
    if confirmed_id and st.button("Сформировать документ"):
        _generate_and_render(application, confirmed_id)


def _render_list(application: ReportApplication) -> None:
    documents = application.repository.list()
    if not documents:
        st.info("Сохранённых документов пока нет.")
        return
    st.dataframe(
        [
            {
                "id": document.id,
                "тип": document.document_type.value,
                "название": document.title,
                "создан": document.created_at,
                "статус": document.status.value,
                "revision": document.revision,
                "устарел": application.repository.is_stale(document.id),
            }
            for document in documents
        ],
        use_container_width=True,
    )


def _render_test_act(application: ReportApplication) -> None:
    protocols = application.repository.list(DocumentType.TEST_PROTOCOL.value)
    available = {f"{item.title or item.id} [{item.status.value}]": item.id for item in protocols}
    selected = st.multiselect("Подтверждённые протоколы", list(available))
    title = st.text_input("Название акта", "Акт испытаний")
    if st.button("Собрать акт испытаний"):
        try:
            act = application.build_test_act([available[label] for label in selected], title)
            st.session_state["test_act_id"] = act.id
            st.json(json.loads(act.model_dump_json()))
            st.success("Структура акта собрана Python-кодом и сохранена")
        except (ValueError, KeyError) as error:
            st.error(str(error))
    act_id = st.session_state.get("test_act_id")
    if act_id and st.button("Сформировать текст и DOCX акта"):
        _generate_and_render(application, act_id)


def _generate_and_render(application: ReportApplication, document_id: str) -> None:
    try:
        document, validation, docx_path = application.generate(document_id)
    except Exception as error:
        st.error(f"Ошибка генерации: {error}")
        return
    st.subheader("Сформированный текст")
    st.write(document.generated_text)
    if validation.issues:
        st.error("Validator обнаружил потенциальные галлюцинации")
        st.dataframe([issue.model_dump(mode="json") for issue in validation.issues])
    elif docx_path:
        st.success("Проверка пройдена")
        path = Path(docx_path)
        st.download_button("Скачать DOCX", path.read_bytes(), file_name=path.name)
