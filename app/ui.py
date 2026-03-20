from __future__ import annotations

import asyncio

import streamlit as st

from app.core.config import get_settings
from app.routes.process_notes import get_orchestrator


def _run_async(coro):
    return asyncio.run(coro)


def _load_tickets(project_key: str | None):
    orchestrator = get_orchestrator()
    normalized_key = project_key.strip().upper() if project_key else None
    return _run_async(orchestrator._jira_client.get_assigned_tickets(project_key=normalized_key))


def _process_notes(notes: str, working_hours: float, ticket_prefix: str | None):
    orchestrator = get_orchestrator()
    normalized_key = ticket_prefix.strip().upper() if ticket_prefix else None
    return _run_async(
        orchestrator.process(
            notes=notes,
            working_hours=working_hours,
            ticket_prefix=normalized_key,
        )
    )


def main() -> None:
    settings = get_settings()

    st.set_page_config(
        page_title="AI Jira Worklog Assistant",
        page_icon="J",
        layout="wide",
    )

    st.title("AI Jira Worklog Assistant")
    st.caption("Convert daily notes into Jira-ready updates and browse assigned tickets by project prefix.")

    with st.sidebar:
        st.subheader("Controls")
        project_key = st.text_input(
            "Ticket Prefix",
            placeholder="GA or ILPQC",
            help="Filter tickets by Jira key prefix. Example: GA returns GA-* tickets only.",
        ).strip().upper()
        working_hours = st.number_input(
            "Working Hours",
            min_value=0.5,
            max_value=24.0,
            value=8.0,
            step=0.5,
        )
        st.caption(f"Jira mode: {'Mock' if settings.jira_use_mock else 'Live Jira'}")

    left_col, right_col = st.columns([1.05, 1.35], gap="large")

    with left_col:
        st.subheader("Assigned Tickets")
        if st.button("Load Tickets", use_container_width=True):
            try:
                tickets = _load_tickets(project_key or None)
                st.session_state["tickets"] = tickets
                st.session_state["ticket_error"] = None
            except Exception as exc:  # pragma: no cover - UI error surface
                st.session_state["tickets"] = []
                st.session_state["ticket_error"] = str(exc)

        ticket_error = st.session_state.get("ticket_error")
        tickets = st.session_state.get("tickets", [])

        if ticket_error:
            st.error(ticket_error)
        elif tickets:
            st.success(f"Loaded {len(tickets)} tickets")
            st.dataframe(
                [
                    {
                        "ticket_id": ticket.ticket_id,
                        "summary": ticket.summary,
                    }
                    for ticket in tickets
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Load tickets to preview assigned Jira issues.")

    with right_col:
        st.subheader("Generate Worklog")
        notes = st.text_area(
            "Daily Notes",
            height=260,
            placeholder="Paste raw notes here. Example: Fixed GA grant transaction bug, updated validation, synced with QA.",
        )

        if st.button("Process Notes", type="primary", use_container_width=True):
            if not notes.strip():
                st.error("Notes are required.")
            else:
                try:
                    result = _process_notes(notes, float(working_hours), project_key or None)
                    st.session_state["result"] = result
                    st.session_state["process_error"] = None
                except Exception as exc:  # pragma: no cover - UI error surface
                    st.session_state["result"] = None
                    st.session_state["process_error"] = str(exc)

        process_error = st.session_state.get("process_error")
        result = st.session_state.get("result")

        if process_error:
            st.error(process_error)
        elif result is not None:
            if result.tickets:
                st.markdown("#### Ticket Updates")
                for ticket in result.tickets:
                    with st.container(border=True):
                        st.markdown(f"**{ticket.ticket_id}**")
                        st.write(f"Suggested time: {ticket.time_hours} hours")
                        for update in ticket.updates:
                            st.write(f"- {update}")
            else:
                st.warning("No tickets were mapped from these notes.")

            st.markdown("#### Unmapped Work")
            if result.unmapped:
                for item in result.unmapped:
                    with st.container(border=True):
                        st.markdown(f"**{item.title}**")
                        st.write(f"Reason: {item.reason}")
                        st.write(f"Suggested time: {item.suggested_time_hours} hours")
                        for detail in item.details:
                            st.write(f"- {detail}")
            else:
                st.success("No unmapped work.")

            st.markdown("#### Raw JSON")
            st.json(result.model_dump(mode="json"))


if __name__ == "__main__":
    main()
