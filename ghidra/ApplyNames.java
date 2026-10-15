// Step 3: apply names.tsv to the analyzed program, create functions Ghidra missed,
// and export the named C for the program's own code (everything before the entry point).
//
// names.tsv format, tab separated:  kind <TAB> address <TAB> name
//   fn      rename the function at that address
//   create  create a function there first (code reached only through a pointer), then name it
//   dat     name a global variable or table
//
// Run by run.py:
//   analyzeHeadless <project_dir> <name> -process ski32.exe -noanalysis -postScript ApplyNames.java names.tsv <out_dir>
//@category SkiFree

import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.nio.file.Files;

public class ApplyNames extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File tsv = new File(args[0]);
        File dir = new File(args.length > 1 ? args[1] : ".");
        dir.mkdirs();

        FunctionManager fm = currentProgram.getFunctionManager();
        SymbolTable st = currentProgram.getSymbolTable();
        int functions = 0, created = 0, globals = 0, failures = 0;

        for (String line : Files.readAllLines(tsv.toPath())) {
            if (line.isBlank() || line.startsWith("#")) continue;
            String[] p = line.split("\t");
            if (p.length < 3) continue;
            String kind = p[0].trim(), name = p[2].trim();
            Address a = toAddr(Long.parseLong(p[1].trim().replace("0x", ""), 16));
            try {
                if (kind.equals("fn") || kind.equals("create")) {
                    Function f = fm.getFunctionAt(a);
                    if (f == null) {
                        disassemble(a);
                        new CreateFunctionCmd(a).applyTo(currentProgram, monitor);
                        f = fm.getFunctionAt(a);
                        if (f != null) created++;
                    }
                    if (f == null) {
                        printerr("Could not create a function at " + a);
                        failures++;
                        continue;
                    }
                    f.setName(name, SourceType.USER_DEFINED);
                    functions++;
                } else if (kind.equals("dat")) {
                    Symbol s = st.getPrimarySymbol(a);
                    if (s != null) s.setName(name, SourceType.USER_DEFINED);
                    else st.createLabel(a, name, SourceType.USER_DEFINED);
                    globals++;
                }
            } catch (Exception e) {
                printerr("Failed " + kind + " " + a + " " + name + ": " + e.getMessage());
                failures++;
            }
        }
        println("ApplyNames: " + functions + " functions (" + created + " created), " + globals + " globals, " + failures + " failures");

        analyzeChanges(currentProgram);

        // The program's own code sits before the C runtime's startup code at the entry point.
        long entry = Long.MAX_VALUE;
        AddressIterator entries = st.getExternalEntryPointIterator();
        while (entries.hasNext()) entry = Math.min(entry, entries.next().getOffset());

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.setSimplificationStyle("decompile");
        decompiler.openProgram(currentProgram);
        int exported = 0;
        try (PrintWriter code = new PrintWriter(new FileWriter(new File(dir, "decompiled.c")));
             PrintWriter list = new PrintWriter(new FileWriter(new File(dir, "functions.tsv")))) {
            list.println("address\tname\tbytes\tcallers\tcallees");
            for (Function f : fm.getFunctions(true)) {
                list.println(f.getEntryPoint() + "\t" + f.getName() + "\t" + f.getBody().getNumAddresses()
                    + "\t" + f.getCallingFunctions(monitor).size() + "\t" + f.getCalledFunctions(monitor).size());
                if (f.isExternal() || f.isThunk() || f.getEntryPoint().getOffset() >= entry) continue;
                DecompileResults res = decompiler.decompileFunction(f, 60, monitor);
                code.println("// ============ " + f.getName() + " @ " + f.getEntryPoint() + " ============");
                code.println(res != null && res.decompileCompleted()
                    ? res.getDecompiledFunction().getC()
                    : "// FAILED: " + (res == null ? "null" : res.getErrorMessage()));
                exported++;
            }
        }
        decompiler.dispose();
        println("ApplyNames: exported " + exported + " functions -> " + dir.getAbsolutePath());
    }
}
