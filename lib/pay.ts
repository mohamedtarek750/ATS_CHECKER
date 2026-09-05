/**
 * Simulated pay data. NOT ACUD's payroll.
 *
 * The workforce dataset this project was built on carries no salary figures at
 * all, and a compensation page needs some to be a compensation page. These were
 * generated once, from a fixed seed, so that they are internally consistent:
 * bands follow seniority, spreads follow team size, and average experience
 * tracks level. Every page that reads them says on its face that they are
 * invented.
 *
 * Three problems were planted deliberately, because an equity report that finds
 * nothing demonstrates nothing:
 *
 *   - Maintenance Technician sits below the market band for its level.
 *   - Auditor (Finance) pays about what a mid-level role pays, though it is
 *     graded Expert - the compression case.
 *   - Software Engineer has a spread far too wide for one job title.
 *   - Operations Manager (Senior) is paid barely more than Facility Manager
 *     (Mid) beside it - the compression case.
 *
 * They are findings, not bugs. Replacing this file with a real payroll export
 * of the same shape is the whole migration - nothing else reads salaries.
 *
 * Amounts are monthly, in EGP.
 *
 * Regenerate: the script that produced this lives in the commit that added it.
 */

export type PayLevel = "Junior" | "Mid" | "Senior" | "Expert";

export interface PayRow {
  department: string;
  role: string;
  level: PayLevel;
  employees: number;
  /** Mean years of experience across the people in this role. */
  avgExperience: number;
  min: number;
  p25: number;
  median: number;
  p75: number;
  max: number;
}

/** What the market pays for each grade. The reference an anomaly is measured against. */
export const BANDS: Record<PayLevel, { low: number; high: number }> = {
  Junior: { low: 12000, high: 22000 },
  Mid: { low: 20000, high: 38000 },
  Senior: { low: 34000, high: 58000 },
  Expert: { low: 52000, high: 92000 },
};

export const PAY: PayRow[] = [
  { department: "Engineering", role: "Civil Engineer", level: "Mid", employees: 34, avgExperience: 5.1, min: 21500, p25: 27500, median: 29500, p75: 33000, max: 39750 },
  { department: "Engineering", role: "Electrical Engineer", level: "Junior", employees: 22, avgExperience: 2.7, min: 12250, p25: 14500, median: 15000, p75: 16500, max: 21750 },
  { department: "Engineering", role: "Mechanical Engineer", level: "Mid", employees: 20, avgExperience: 4.7, min: 21250, p25: 24500, median: 28500, p75: 31500, max: 37000 },
  { department: "Engineering", role: "Project Engineer", level: "Junior", employees: 30, avgExperience: 2.1, min: 13750, p25: 15250, median: 17000, p75: 18750, max: 21750 },
  { department: "Engineering", role: "Quality Engineer", level: "Junior", employees: 19, avgExperience: 1.9, min: 14750, p25: 17000, median: 18750, p75: 19500, max: 21750 },
  { department: "Finance", role: "Accountant", level: "Expert", employees: 11, avgExperience: 12.4, min: 50250, p25: 67500, median: 75500, p75: 84500, max: 87000 },
  { department: "Finance", role: "Auditor", level: "Expert", employees: 17, avgExperience: 12.2, min: 35250, p25: 38500, median: 41250, p75: 43250, max: 48000 },
  { department: "Finance", role: "Budget Analyst", level: "Junior", employees: 13, avgExperience: 2.8, min: 13500, p25: 16500, median: 17500, p75: 18750, max: 20250 },
  { department: "Finance", role: "Financial Analyst", level: "Mid", employees: 13, avgExperience: 4.7, min: 27750, p25: 29250, median: 29500, p75: 31000, max: 36500 },
  { department: "Human Resources", role: "Compensation Analyst", level: "Senior", employees: 11, avgExperience: 10.8, min: 33250, p25: 43250, median: 47500, p75: 49000, max: 51500 },
  { department: "Human Resources", role: "Hr Specialist", level: "Junior", employees: 7, avgExperience: 3.2, min: 16250, p25: 17000, median: 17500, p75: 19000, max: 19000 },
  { department: "Human Resources", role: "Talent Acquisition", level: "Senior", employees: 3, avgExperience: 7.2, min: 38250, p25: 39000, median: 39500, p75: 41000, max: 42250 },
  { department: "Human Resources", role: "Training Coordinator", level: "Senior", employees: 8, avgExperience: 8.8, min: 32500, p25: 38750, median: 43250, p75: 47500, max: 48000 },
  { department: "Information Technology", role: "Cybersecurity Specialist", level: "Mid", employees: 16, avgExperience: 4.4, min: 25000, p25: 28250, median: 31500, p75: 32250, max: 36750 },
  { department: "Information Technology", role: "Data Analyst", level: "Junior", employees: 12, avgExperience: 2.6, min: 15500, p25: 17500, median: 18000, p75: 19000, max: 25250 },
  { department: "Information Technology", role: "Data Scientist", level: "Mid", employees: 7, avgExperience: 4.6, min: 27250, p25: 29500, median: 29750, p75: 33000, max: 36250 },
  { department: "Information Technology", role: "Devops Engineer", level: "Junior", employees: 11, avgExperience: 1.8, min: 14500, p25: 16500, median: 17500, p75: 18500, max: 19750 },
  { department: "Information Technology", role: "IT Support", level: "Senior", employees: 9, avgExperience: 8.2, min: 35750, p25: 39750, median: 50750, p75: 54500, max: 58000 },
  { department: "Information Technology", role: "Software Engineer", level: "Expert", employees: 22, avgExperience: 13.5, min: 38250, p25: 59750, median: 82500, p75: 92500, max: 104250 },
  { department: "Legal", role: "Compliance Officer", level: "Mid", employees: 9, avgExperience: 4.6, min: 25250, p25: 29000, median: 31500, p75: 32750, max: 37500 },
  { department: "Legal", role: "Contract Specialist", level: "Mid", employees: 5, avgExperience: 5.4, min: 21750, p25: 24250, median: 24500, p75: 24750, max: 27000 },
  { department: "Legal", role: "Legal Counsel", level: "Mid", employees: 4, avgExperience: 4.2, min: 25500, p25: 27750, median: 28750, p75: 30000, max: 33250 },
  { department: "Operations", role: "Facility Manager", level: "Mid", employees: 21, avgExperience: 5.5, min: 27000, p25: 29000, median: 30750, p75: 33500, max: 35750 },
  { department: "Operations", role: "Logistics Coordinator", level: "Senior", employees: 23, avgExperience: 9.2, min: 36500, p25: 41000, median: 43250, p75: 47500, max: 55500 },
  { department: "Operations", role: "Maintenance Technician", level: "Mid", employees: 22, avgExperience: 4.2, min: 11250, p25: 15500, median: 17250, p75: 18500, max: 22250 },
  { department: "Operations", role: "Operations Manager", level: "Senior", employees: 15, avgExperience: 9.6, min: 21250, p25: 26500, median: 29750, p75: 32000, max: 34250 },
  { department: "Project Management", role: "PMO Analyst", level: "Mid", employees: 12, avgExperience: 5.0, min: 23750, p25: 27000, median: 30000, p75: 32750, max: 36500 },
  { department: "Project Management", role: "Project Coordinator", level: "Junior", employees: 17, avgExperience: 2.0, min: 13000, p25: 14250, median: 15750, p75: 19000, max: 21000 },
  { department: "Project Management", role: "Project Manager", level: "Expert", employees: 22, avgExperience: 13.2, min: 54250, p25: 66500, median: 73000, p75: 79750, max: 88500 },
  { department: "Project Management", role: "Scrum Master", level: "Senior", employees: 14, avgExperience: 10.1, min: 27250, p25: 46750, median: 51500, p75: 55000, max: 61500 },
  { department: "Sales & Marketing", role: "Content Creator", level: "Mid", employees: 17, avgExperience: 5.5, min: 22250, p25: 25750, median: 26750, p75: 30500, max: 35750 },
  { department: "Sales & Marketing", role: "Digital Marketing Analyst", level: "Mid", employees: 10, avgExperience: 6.8, min: 22250, p25: 24500, median: 25500, p75: 27750, max: 30250 },
  { department: "Sales & Marketing", role: "Marketing Specialist", level: "Junior", employees: 6, avgExperience: 3.1, min: 14500, p25: 16250, median: 17750, p75: 18000, max: 18250 },
];
