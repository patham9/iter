import js

DESCRIPTION = "Adds a Hello drawer with World as its content."

def transform(messages, tools):
    doc = js.document
    if not doc.getElementById("gui-example"):
        activity = doc.getElementById("activity-drawer")
        if activity:
            drawer = doc.createElement("details")
            drawer.id = "gui-example"
            drawer.setAttribute("open", "")
            summary = doc.createElement("summary")
            summary.textContent = "GUI example"
            content = doc.createElement("div")
            content.textContent = "Hello world!"
            drawer.appendChild(summary)
            drawer.appendChild(content)
            activity.parentElement.insertBefore(drawer, activity.nextSibling)
    return messages, tools
