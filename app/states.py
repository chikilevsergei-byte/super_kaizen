from aiogram.fsm.state import StatesGroup, State

class OnboardingForm(StatesGroup):
    role = State()
    password = State()
    employee_region = State()
    employee_cluster = State()
    employee_store = State()
    supervisor_region = State()
    supervisor_cluster = State()
    region_select = State()

class ProblemForm(StatesGroup):
    text = State()
    store = State()
    store_id = State()
    store_name = State()
    confirm_duplicate = State()

class AdminForm(StatesGroup):
    action = State()

class StatusUpdateForm(StatesGroup):
    selecting_problem = State()
    selecting_status = State()
    entering_comment = State()

class FeedbackForm(StatesGroup):
    text = State()
    phone = State()
