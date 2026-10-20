#include "crash_database.h"

#include "base/files/file_path.h"
#include "client/crash_report_database.h"

#if defined(_WIN32)
#include "base/strings/utf_string_conversions.h"
#endif

#include <memory>

namespace {

base::FilePath _to_path(const std::string &p_utf8) {
#if defined(_WIN32)
	return base::FilePath(base::UTF8ToWide(p_utf8));
#else
	return base::FilePath(p_utf8);
#endif
}

// Never creates a database: a game that never started Crashpad has nothing waiting.
std::unique_ptr<crashpad::CrashReportDatabase> _open(const std::string &p_database_path) {
	return crashpad::CrashReportDatabase::InitializeWithoutCreating(_to_path(p_database_path));
}

std::vector<crashpad::CrashReportDatabase::Report> _pending(crashpad::CrashReportDatabase *p_db) {
	std::vector<crashpad::CrashReportDatabase::Report> reports;
	if (p_db == nullptr || p_db->GetPendingReports(&reports) != crashpad::CrashReportDatabase::kNoError) {
		reports.clear();
	}
	return reports;
}

} // unnamed namespace

namespace sentry::native::crash_database {

std::vector<PendingReport> pending_reports(const std::string &p_database_path) {
	std::vector<PendingReport> found;
	std::unique_ptr<crashpad::CrashReportDatabase> db = _open(p_database_path);
	for (const crashpad::CrashReportDatabase::Report &report : _pending(db.get())) {
		found.push_back({ report.uuid.ToString(), (int64_t)report.creation_time });
	}
	return found;
}

int delete_pending_reports(const std::string &p_database_path) {
	int deleted = 0;
	std::unique_ptr<crashpad::CrashReportDatabase> db = _open(p_database_path);
	for (const crashpad::CrashReportDatabase::Report &report : _pending(db.get())) {
		if (db->DeleteReport(report.uuid) == crashpad::CrashReportDatabase::kNoError) {
			deleted++;
		}
	}
	return deleted;
}

} //namespace sentry::native::crash_database
