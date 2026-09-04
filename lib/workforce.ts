/**
 * The workforce planning figures.
 *
 * IMPORTANT, and surfaced in the UI rather than buried here: this is a FROZEN
 * FORECAST, not live data. It came out of a Lasso regression trained once on
 * quarterly staffing records (2020–2026) and exported. Nothing in the running
 * system updates it, and no applicant affects it.
 *
 * That matters because it sits next to the ATS, whose numbers ARE live and do
 * change every time somebody applies. Two kinds of number on one screen, one of
 * which is a snapshot and one of which is current, is exactly how a reader comes
 * to trust the wrong one. Every page built on this data says where it came from.
 */

export interface Department {
  Department: string;
  Current: number;
  Predicted: number;
  Gap: number;
  Roles: number;
}

export interface RoleForecast {
  Department: string;
  Job_Role: string;
  Current_Employees: number;
  Predicted_Workforce_Demand: number;
  Predicted_Workforce_Gap: number;
}

export interface PerformanceTier {
  department: string;
  role: string;
  score: number;
  employees: number;
  tier: "bonus" | "normal" | "improve";
}

export interface TurnoverRow {
  department: string;
  role: string;
  turnover_rate: number;
  employees_lost: number;
  net_change: number;
  current_employees: number;
  risk: "high" | "medium" | "low";
}

export interface CostRole {
  department: string;
  role: string;
  gap: number;
  level: "Junior" | "Mid" | "Senior" | "Expert";
}

/** When the forecast was produced. Shown wherever its numbers are. */
export const FORECAST = {
  model: "Lasso Regression",
  trainedOn: "quarterly staffing records, 2020–2026",
  r2: 0.952,
  mae: 1.5,
  note:
    "Evaluated on the most recent year, held out chronologically. It explains " +
    "95.2% of the variation in workforce demand (R²) with an average error of " +
    "±1.5 employees per role (MAE).",
};

export const DEPARTMENTS: Department[] = [
  { Department: "Engineering", Current: 125, Predicted: 137, Gap: 12, Roles: 5 },
  { Department: "Information Technology", Current: 77, Predicted: 89, Gap: 12, Roles: 6 },
  { Department: "Finance", Current: 54, Predicted: 64, Gap: 10, Roles: 4 },
  { Department: "Operations", Current: 81, Predicted: 90, Gap: 9, Roles: 4 },
  { Department: "Project Management", Current: 65, Predicted: 73, Gap: 8, Roles: 4 },
  { Department: "Human Resources", Current: 29, Predicted: 36, Gap: 7, Roles: 4 },
  { Department: "Legal", Current: 18, Predicted: 24, Gap: 6, Roles: 3 },
  { Department: "Sales & Marketing", Current: 33, Predicted: 37, Gap: 4, Roles: 3 },
];

export const ROLES: RoleForecast[] = [
  { Department: "Engineering", Job_Role: "Civil Engineer", Current_Employees: 34, Predicted_Workforce_Demand: 37, Predicted_Workforce_Gap: 3 },
  { Department: "Engineering", Job_Role: "Project Engineer", Current_Employees: 30, Predicted_Workforce_Demand: 33, Predicted_Workforce_Gap: 3 },
  { Department: "Finance", Job_Role: "Auditor", Current_Employees: 17, Predicted_Workforce_Demand: 20, Predicted_Workforce_Gap: 3 },
  { Department: "Finance", Job_Role: "Financial Analyst", Current_Employees: 13, Predicted_Workforce_Demand: 16, Predicted_Workforce_Gap: 3 },
  { Department: "Operations", Job_Role: "Maintenance Technician", Current_Employees: 22, Predicted_Workforce_Demand: 25, Predicted_Workforce_Gap: 3 },
  { Department: "Engineering", Job_Role: "Quality Engineer", Current_Employees: 19, Predicted_Workforce_Demand: 21, Predicted_Workforce_Gap: 2 },
  { Department: "Engineering", Job_Role: "Mechanical Engineer", Current_Employees: 20, Predicted_Workforce_Demand: 22, Predicted_Workforce_Gap: 2 },
  { Department: "Finance", Job_Role: "Accountant", Current_Employees: 11, Predicted_Workforce_Demand: 13, Predicted_Workforce_Gap: 2 },
  { Department: "Engineering", Job_Role: "Electrical Engineer", Current_Employees: 22, Predicted_Workforce_Demand: 24, Predicted_Workforce_Gap: 2 },
  { Department: "Human Resources", Job_Role: "Compensation Analyst", Current_Employees: 11, Predicted_Workforce_Demand: 13, Predicted_Workforce_Gap: 2 },
  { Department: "Human Resources", Job_Role: "Talent Acquisition", Current_Employees: 3, Predicted_Workforce_Demand: 5, Predicted_Workforce_Gap: 2 },
  { Department: "Human Resources", Job_Role: "Training Coordinator", Current_Employees: 8, Predicted_Workforce_Demand: 10, Predicted_Workforce_Gap: 2 },
  { Department: "Information Technology", Job_Role: "Cybersecurity Specialist", Current_Employees: 16, Predicted_Workforce_Demand: 18, Predicted_Workforce_Gap: 2 },
  { Department: "Information Technology", Job_Role: "Data Scientist", Current_Employees: 7, Predicted_Workforce_Demand: 9, Predicted_Workforce_Gap: 2 },
  { Department: "Information Technology", Job_Role: "Data Analyst", Current_Employees: 12, Predicted_Workforce_Demand: 14, Predicted_Workforce_Gap: 2 },
  { Department: "Information Technology", Job_Role: "Devops Engineer", Current_Employees: 11, Predicted_Workforce_Demand: 13, Predicted_Workforce_Gap: 2 },
  { Department: "Finance", Job_Role: "Budget Analyst", Current_Employees: 13, Predicted_Workforce_Demand: 15, Predicted_Workforce_Gap: 2 },
  { Department: "Project Management", Job_Role: "PMO Analyst", Current_Employees: 12, Predicted_Workforce_Demand: 14, Predicted_Workforce_Gap: 2 },
  { Department: "Information Technology", Job_Role: "IT Support", Current_Employees: 9, Predicted_Workforce_Demand: 11, Predicted_Workforce_Gap: 2 },
  { Department: "Legal", Job_Role: "Compliance Officer", Current_Employees: 9, Predicted_Workforce_Demand: 11, Predicted_Workforce_Gap: 2 },
  { Department: "Information Technology", Job_Role: "Software Engineer", Current_Employees: 22, Predicted_Workforce_Demand: 24, Predicted_Workforce_Gap: 2 },
  { Department: "Legal", Job_Role: "Legal Counsel", Current_Employees: 4, Predicted_Workforce_Demand: 6, Predicted_Workforce_Gap: 2 },
  { Department: "Sales & Marketing", Job_Role: "Content Creator", Current_Employees: 17, Predicted_Workforce_Demand: 19, Predicted_Workforce_Gap: 2 },
  { Department: "Operations", Job_Role: "Facility Manager", Current_Employees: 21, Predicted_Workforce_Demand: 23, Predicted_Workforce_Gap: 2 },
  { Department: "Legal", Job_Role: "Contract Specialist", Current_Employees: 5, Predicted_Workforce_Demand: 7, Predicted_Workforce_Gap: 2 },
  { Department: "Project Management", Job_Role: "Project Manager", Current_Employees: 22, Predicted_Workforce_Demand: 24, Predicted_Workforce_Gap: 2 },
  { Department: "Project Management", Job_Role: "Project Coordinator", Current_Employees: 17, Predicted_Workforce_Demand: 19, Predicted_Workforce_Gap: 2 },
  { Department: "Operations", Job_Role: "Logistics Coordinator", Current_Employees: 23, Predicted_Workforce_Demand: 25, Predicted_Workforce_Gap: 2 },
  { Department: "Operations", Job_Role: "Operations Manager", Current_Employees: 15, Predicted_Workforce_Demand: 17, Predicted_Workforce_Gap: 2 },
  { Department: "Project Management", Job_Role: "Scrum Master", Current_Employees: 14, Predicted_Workforce_Demand: 16, Predicted_Workforce_Gap: 2 },
  { Department: "Human Resources", Job_Role: "Hr Specialist", Current_Employees: 7, Predicted_Workforce_Demand: 8, Predicted_Workforce_Gap: 1 },
  { Department: "Sales & Marketing", Job_Role: "Marketing Specialist", Current_Employees: 6, Predicted_Workforce_Demand: 7, Predicted_Workforce_Gap: 1 },
  { Department: "Sales & Marketing", Job_Role: "Digital Marketing Analyst", Current_Employees: 10, Predicted_Workforce_Demand: 11, Predicted_Workforce_Gap: 1 },
];

export const TOTALS = {
  current: 482,
  predicted: 550,
  gap: 68,
  departments: 8,
  roles: 33,
  avgPerformance: 3.8,
  avgExperience: 7.91,
};

export const DEPARTMENT_PERFORMANCE = [
  { Department: "Operations", Avg_Performance: 4.08, Avg_Experience: 7.2 },
  { Department: "Finance", Avg_Performance: 3.92, Avg_Experience: 9.6 },
  { Department: "Project Management", Avg_Performance: 3.9, Avg_Experience: 7.1 },
  { Department: "Information Technology", Avg_Performance: 3.82, Avg_Experience: 7.02 },
  { Department: "Sales & Marketing", Avg_Performance: 3.77, Avg_Experience: 8.7 },
  { Department: "Engineering", Avg_Performance: 3.76, Avg_Experience: 7.36 },
  { Department: "Legal", Avg_Performance: 3.67, Avg_Experience: 8.17 },
  { Department: "Human Resources", Avg_Performance: 3.48, Avg_Experience: 8.98 },
];

export const PERFORMANCE_TIERS: PerformanceTier[] = [
  { department: "Information Technology", role: "Software Engineer", score: 4.7, employees: 22, tier: "bonus" },
  { department: "Information Technology", role: "Cybersecurity Specialist", score: 4.5, employees: 16, tier: "bonus" },
  { department: "Engineering", role: "Quality Engineer", score: 4.5, employees: 19, tier: "bonus" },
  { department: "Operations", role: "Facility Manager", score: 4.3, employees: 21, tier: "bonus" },
  { department: "Finance", role: "Auditor", score: 4.3, employees: 17, tier: "bonus" },
  { department: "Project Management", role: "Project Manager", score: 4.3, employees: 22, tier: "bonus" },
  { department: "Project Management", role: "Project Coordinator", score: 4.3, employees: 17, tier: "bonus" },
  { department: "Sales & Marketing", role: "Marketing Specialist", score: 4.2, employees: 6, tier: "bonus" },
  { department: "Operations", role: "Maintenance Technician", score: 4.2, employees: 22, tier: "bonus" },
  { department: "Finance", role: "Budget Analyst", score: 4.1, employees: 13, tier: "bonus" },
  { department: "Operations", role: "Logistics Coordinator", score: 4.1, employees: 23, tier: "bonus" },
  { department: "Engineering", role: "Mechanical Engineer", score: 3.9, employees: 20, tier: "normal" },
  { department: "Information Technology", role: "Data Scientist", score: 3.9, employees: 7, tier: "normal" },
  { department: "Finance", role: "Financial Analyst", score: 3.8, employees: 13, tier: "normal" },
  { department: "Legal", role: "Legal Counsel", score: 3.8, employees: 4, tier: "normal" },
  { department: "Legal", role: "Compliance Officer", score: 3.8, employees: 9, tier: "normal" },
  { department: "Project Management", role: "PMO Analyst", score: 3.7, employees: 12, tier: "normal" },
  { department: "Operations", role: "Operations Manager", score: 3.7, employees: 15, tier: "normal" },
  { department: "Engineering", role: "Civil Engineer", score: 3.6, employees: 34, tier: "normal" },
  { department: "Engineering", role: "Electrical Engineer", score: 3.6, employees: 22, tier: "normal" },
  { department: "Sales & Marketing", role: "Content Creator", score: 3.6, employees: 17, tier: "normal" },
  { department: "Human Resources", role: "Training Coordinator", score: 3.6, employees: 8, tier: "normal" },
  { department: "Human Resources", role: "Hr Specialist", score: 3.6, employees: 7, tier: "normal" },
  { department: "Sales & Marketing", role: "Digital Marketing Analyst", score: 3.5, employees: 10, tier: "normal" },
  { department: "Finance", role: "Accountant", score: 3.5, employees: 11, tier: "normal" },
  { department: "Information Technology", role: "Data Analyst", score: 3.4, employees: 12, tier: "improve" },
  { department: "Legal", role: "Contract Specialist", score: 3.4, employees: 5, tier: "improve" },
  { department: "Human Resources", role: "Talent Acquisition", score: 3.4, employees: 3, tier: "improve" },
  { department: "Human Resources", role: "Compensation Analyst", score: 3.3, employees: 11, tier: "improve" },
  { department: "Project Management", role: "Scrum Master", score: 3.3, employees: 14, tier: "improve" },
  { department: "Engineering", role: "Project Engineer", score: 3.2, employees: 30, tier: "improve" },
  { department: "Information Technology", role: "Devops Engineer", score: 3.2, employees: 11, tier: "improve" },
  { department: "Information Technology", role: "IT Support", score: 3.2, employees: 9, tier: "improve" },
];

export const TURNOVER: TurnoverRow[] = [
  { department: "Human Resources", role: "Talent Acquisition", turnover_rate: 33.3, employees_lost: 1, net_change: -1, current_employees: 3, risk: "high" },
  { department: "Finance", role: "Auditor", turnover_rate: 17.6, employees_lost: 3, net_change: -2, current_employees: 17, risk: "high" },
  { department: "Sales & Marketing", role: "Marketing Specialist", turnover_rate: 16.7, employees_lost: 1, net_change: -1, current_employees: 6, risk: "high" },
  { department: "Information Technology", role: "IT Support", turnover_rate: 11.1, employees_lost: 1, net_change: 0, current_employees: 9, risk: "medium" },
  { department: "Sales & Marketing", role: "Digital Marketing Analyst", turnover_rate: 10.0, employees_lost: 1, net_change: 0, current_employees: 10, risk: "medium" },
  { department: "Operations", role: "Facility Manager", turnover_rate: 9.5, employees_lost: 2, net_change: -2, current_employees: 21, risk: "medium" },
  { department: "Project Management", role: "Project Manager", turnover_rate: 9.1, employees_lost: 2, net_change: 0, current_employees: 22, risk: "medium" },
  { department: "Human Resources", role: "Compensation Analyst", turnover_rate: 9.1, employees_lost: 1, net_change: 0, current_employees: 11, risk: "medium" },
  { department: "Information Technology", role: "Devops Engineer", turnover_rate: 9.1, employees_lost: 1, net_change: 0, current_employees: 11, risk: "medium" },
  { department: "Operations", role: "Maintenance Technician", turnover_rate: 9.1, employees_lost: 2, net_change: -2, current_employees: 22, risk: "medium" },
  { department: "Engineering", role: "Civil Engineer", turnover_rate: 8.8, employees_lost: 3, net_change: 2, current_employees: 34, risk: "medium" },
  { department: "Information Technology", role: "Data Analyst", turnover_rate: 8.3, employees_lost: 1, net_change: -1, current_employees: 12, risk: "medium" },
  { department: "Finance", role: "Financial Analyst", turnover_rate: 7.7, employees_lost: 1, net_change: -1, current_employees: 13, risk: "low" },
  { department: "Engineering", role: "Project Engineer", turnover_rate: 6.7, employees_lost: 2, net_change: 1, current_employees: 30, risk: "low" },
  { department: "Operations", role: "Operations Manager", turnover_rate: 6.7, employees_lost: 1, net_change: 1, current_employees: 15, risk: "low" },
  { department: "Information Technology", role: "Cybersecurity Specialist", turnover_rate: 6.2, employees_lost: 1, net_change: -1, current_employees: 16, risk: "low" },
  { department: "Engineering", role: "Quality Engineer", turnover_rate: 5.3, employees_lost: 1, net_change: 2, current_employees: 19, risk: "low" },
  { department: "Engineering", role: "Mechanical Engineer", turnover_rate: 5.0, employees_lost: 1, net_change: 1, current_employees: 20, risk: "low" },
  { department: "Information Technology", role: "Software Engineer", turnover_rate: 4.5, employees_lost: 1, net_change: 2, current_employees: 22, risk: "low" },
  { department: "Information Technology", role: "Data Scientist", turnover_rate: 0.0, employees_lost: 0, net_change: 2, current_employees: 7, risk: "low" },
  { department: "Human Resources", role: "Training Coordinator", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 8, risk: "low" },
  { department: "Finance", role: "Accountant", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 11, risk: "low" },
  { department: "Engineering", role: "Electrical Engineer", turnover_rate: 0.0, employees_lost: 0, net_change: 3, current_employees: 22, risk: "low" },
  { department: "Human Resources", role: "Hr Specialist", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 7, risk: "low" },
  { department: "Finance", role: "Budget Analyst", turnover_rate: 0.0, employees_lost: 0, net_change: 1, current_employees: 13, risk: "low" },
  { department: "Legal", role: "Legal Counsel", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 4, risk: "low" },
  { department: "Sales & Marketing", role: "Content Creator", turnover_rate: 0.0, employees_lost: 0, net_change: 1, current_employees: 17, risk: "low" },
  { department: "Legal", role: "Compliance Officer", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 9, risk: "low" },
  { department: "Legal", role: "Contract Specialist", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 5, risk: "low" },
  { department: "Operations", role: "Logistics Coordinator", turnover_rate: 0.0, employees_lost: 0, net_change: 4, current_employees: 23, risk: "low" },
  { department: "Project Management", role: "PMO Analyst", turnover_rate: 0.0, employees_lost: 0, net_change: 0, current_employees: 12, risk: "low" },
  { department: "Project Management", role: "Project Coordinator", turnover_rate: 0.0, employees_lost: 0, net_change: 2, current_employees: 17, risk: "low" },
  { department: "Project Management", role: "Scrum Master", turnover_rate: 0.0, employees_lost: 0, net_change: 2, current_employees: 14, risk: "low" },
];

export const COST_ROLES: CostRole[] = [
  { department: "Finance", role: "Auditor", gap: 3, level: "Expert" },
  { department: "Project Management", role: "Project Manager", gap: 2, level: "Expert" },
  { department: "Finance", role: "Accountant", gap: 2, level: "Expert" },
  { department: "Information Technology", role: "Software Engineer", gap: 2, level: "Expert" },
  { department: "Information Technology", role: "IT Support", gap: 2, level: "Senior" },
  { department: "Human Resources", role: "Training Coordinator", gap: 2, level: "Senior" },
  { department: "Operations", role: "Logistics Coordinator", gap: 2, level: "Senior" },
  { department: "Human Resources", role: "Talent Acquisition", gap: 2, level: "Senior" },
  { department: "Human Resources", role: "Compensation Analyst", gap: 2, level: "Senior" },
  { department: "Project Management", role: "Scrum Master", gap: 2, level: "Senior" },
  { department: "Operations", role: "Operations Manager", gap: 2, level: "Senior" },
  { department: "Engineering", role: "Civil Engineer", gap: 3, level: "Mid" },
  { department: "Operations", role: "Maintenance Technician", gap: 3, level: "Mid" },
  { department: "Finance", role: "Financial Analyst", gap: 3, level: "Mid" },
  { department: "Information Technology", role: "Data Scientist", gap: 2, level: "Mid" },
  { department: "Information Technology", role: "Cybersecurity Specialist", gap: 2, level: "Mid" },
  { department: "Engineering", role: "Mechanical Engineer", gap: 2, level: "Mid" },
  { department: "Legal", role: "Contract Specialist", gap: 2, level: "Mid" },
  { department: "Operations", role: "Facility Manager", gap: 2, level: "Mid" },
  { department: "Sales & Marketing", role: "Content Creator", gap: 2, level: "Mid" },
  { department: "Legal", role: "Legal Counsel", gap: 2, level: "Mid" },
  { department: "Project Management", role: "PMO Analyst", gap: 2, level: "Mid" },
  { department: "Legal", role: "Compliance Officer", gap: 2, level: "Mid" },
  { department: "Engineering", role: "Project Engineer", gap: 3, level: "Junior" },
  { department: "Engineering", role: "Electrical Engineer", gap: 2, level: "Junior" },
  { department: "Engineering", role: "Quality Engineer", gap: 2, level: "Junior" },
  { department: "Information Technology", role: "Devops Engineer", gap: 2, level: "Junior" },
  { department: "Information Technology", role: "Data Analyst", gap: 2, level: "Junior" },
  { department: "Finance", role: "Budget Analyst", gap: 2, level: "Junior" },
  { department: "Project Management", role: "Project Coordinator", gap: 2, level: "Junior" },
  { department: "Sales & Marketing", role: "Digital Marketing Analyst", gap: 1, level: "Mid" },
  { department: "Human Resources", role: "Hr Specialist", gap: 1, level: "Junior" },
  { department: "Sales & Marketing", role: "Marketing Specialist", gap: 1, level: "Junior" },
];

/** Illustrative only — the dataset carries no real cost figures. */
export const DEFAULT_COST_PER_HIRE: Record<CostRole["level"], number> = {
  Junior: 3000,
  Mid: 5000,
  Senior: 8000,
  Expert: 12000,
};

export function urgency(gap: number, current: number): "critical" | "high" | "moderate" {
  const share = current ? gap / current : 0;
  if (share >= 0.2) return "critical";
  if (share >= 0.12) return "high";
  return "moderate";
}
