
__version__ = '0.0.1'

# Monthly Attendance Sheet: make Company filter optional (all companies by default)
try:
	from employee_app.monthly_attendance_sheet import apply as _apply_mas_override

	_apply_mas_override()
except Exception:
	pass

