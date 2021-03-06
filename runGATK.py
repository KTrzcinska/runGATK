import subprocess
import argparse
import os

'''
Do prawidlowego dzialania skryptu wymagane jest:
- podanie sciezki do programow GATK oraz Picard, a w przypadku podania jako pliku wejsciowego pliku fastq rowniez sciezki do BWA
- podanie sciezki do katalogu zawierajacego pliki referencyjne pochodzace z
  GATK bundle ftp://gsapubftp-anonymous@ftp.broadinstitute.org/bundle/
        -Homo_sapiens_assembly38.fasta
        -Homo_sapiens_assembly38.dbsnp.vcf
        -hapmap_3.3.hg38.vcf
        -1000G_omni2.5.hg38.vcf
        -1000G_phase1.snps.high_confidence.hg38.vcf
        -Mills_and_1000G_gold_standard.indels.hg38.vcf
'''

parser = argparse.ArgumentParser()
parser.add_argument("-f","--file",help="SAM or Fastq file",type=str, required=True)
parser.add_argument("-g","--gatk",help="Path to GATK",type=str, required=True)
parser.add_argument("-p","--picard",help="Path to Picard",type=str, required=True)
parser.add_argument("-b","--bwa",help="Path to BWA",type=str, required=False)
parser.add_argument("-r","--ref",help="Reference files directory",type=str, required=True)
args = parser.parse_args()

fileName, fileExtension = os.path.splitext(args.file)
if fileExtension and fileExtension not in ['.sam', '.fastq', '.fq']:
    raise Exception('Error - not valid file type')

if not (os.path.isfile(args.picard) and os.path.isfile(args.gatk)):
    raise Exception('Error - not valid directory')
if not os.path.isdir(args.ref):
    raise Exception('Error - not valid ref directory')

if args.ref.endswith('/'):
    args.ref = args.ref[:-1]

def runProcess(command):
    print command
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    process.wait()

    if process.returncode == 1:
        exit(1)

#In case of fastq file additional BWA mapping step
if fileExtension in ['.fastq', '.fq']:
    if not args.bwa :
        raise Exception('Error - specify BWA directory')
    command = args.bwa + " mem -R '@RG\\tID:group1\\tSM:sample1\\tPL:illumina\\tLB:lib1\\tPU:unit1' -p " + args.ref + "/Homo_sapiens_assembly38.fasta " + args.file + " > " + fileName + ".sam"
    runProcess(command)

#Add RG and coordinate sort
command = 'java -Xmx3g -jar ' + args.picard + ' AddOrReplaceReadGroups I=' + fileName + '.sam O=' + fileName + '_mapped_rg.bam SORT_ORDER=coordinate RGID=1 RGLB=lib1 RGPL=illumina RGPU=unit1 RGSM=I'
runProcess(command)

#Mark duplicates
command = 'java -Xmx3g -jar ' + args.picard + ' MarkDuplicates I=' + fileName + '_mapped_rg.bam O=' + fileName + '_marked_duplicates_rg.bam M=' + fileName + '_marked_dup_metrics_rg.txt CREATE_INDEX=true'
runProcess(command)

#Create target list of intervals to be realigned
command = 'java -Xmx3g -jar ' + args.gatk + ' -T RealignerTargetCreator -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -I ' + fileName + '_marked_duplicates_rg.bam -o ' + fileName + '_forIndelRealigner.intervals.list'
runProcess(command)

command = 'java -Xmx3g -jar ' + args.gatk + ' -T IndelRealigner -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -I ' + fileName + '_marked_duplicates_rg.bam -targetIntervals ' + fileName + '_forIndelRealigner.intervals.list -o ' + fileName + '_realignedBam.bam'
runProcess(command)

#Base recalibration
command = 'java -Xmx3g -jar ' + args.gatk + ' -T BaseRecalibrator -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -I ' + fileName + '_realignedBam.bam -knownSites ' + args.ref + '/Homo_sapiens_assembly38.dbsnp.vcf -o ' + fileName + '_recal_data.table'
runProcess(command)

#Apply the recalibration to sequence data
command = 'java -Xmx3g -jar ' + args.gatk + ' -T PrintReads -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -I ' + fileName + '_realignedBam.bam -BQSR ' + fileName + '_recal_data.table -o ' + fileName + '_recal_reads.bam'
runProcess(command)

#Variant calling
command = 'java -Xmx3g -jar ' + args.gatk + ' -T HaplotypeCaller -I ' + fileName + '_recal_reads.bam -R ' + args.ref + '/Homo_sapiens_assembly38.fasta --output_mode EMIT_VARIANTS_ONLY -ploidy 2 -o ' + fileName + '_raw_variants.vcf'
runProcess(command)

#dbSNP annotation
command = 'java -Xmx3g -jar ' + args.gatk + ' -T VariantAnnotator -R ' + args.ref + '/Homo_sapiens_assembly38.fasta --variant ' + fileName + '_raw_variants.vcf --dbsnp ' + args.ref + '/Homo_sapiens_assembly38.dbsnp.vcf -L ' + fileName + '_raw_variants.vcf -o ' + fileName + '_annotated_raw_variants.vcf'
runProcess(command)

#Variant recalibrator
command = 'java -Xmx3g -jar ' + args.gatk + ' -T VariantRecalibrator -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -input ' + fileName + '_raw_variants.vcf  -resource:hapmap,known=false,training=true,truth=true,prior=15.0 ' + args.ref + '/hapmap_3.3.hg38.vcf -resource:omni,known=false,training=true,truth=true,prior=12.0 ' + args.ref + '/1000G_omni2.5.hg38.vcf -resource:1000G,known=false,training=true,truth=false,prior=10.0 ' + args.ref + '/1000G_phase1.snps.high_confidence.hg38.vcf -resource:dbsnp,known=true,training=false,truth=false,prior=2.0 ' + args.ref + '/Homo_sapiens_assembly38.dbsnp.vcf -an DP -an QD -an MQRankSum -an ReadPosRankSum -an FS -an SOR -mode SNP -tranche 100.0 -tranche 99.9 -tranche 99.0 -tranche 90.0 -recalFile ' + fileName + '_recalibrate_SNP.recal -tranchesFile ' + fileName + '_recalibrate_SNP.tranches'
runProcess(command)

#Apply SNP Recalibration
command = 'java -Xmx3g -jar ' + args.gatk + ' -T ApplyRecalibration  -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -input ' + fileName + '_raw_variants.vcf  -mode SNP --ts_filter_level 99.0 -recalFile ' + fileName + '_recalibrate_SNP.recal -tranchesFile ' + fileName + '_recalibrate_SNP.tranches -o ' + fileName + '_recalibrated_snps_raw_indels.vcf'
runProcess(command)

#Build the Indel recalibration model
command = 'java -Xmx3g -jar ' + args.gatk + ' -T VariantRecalibrator  -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -input ' + fileName + '_recalibrated_snps_raw_indels.vcf -resource:mills,known=false,training=true,truth=true,prior=12.0 ' + args.ref + '/Mills_and_1000G_gold_standard.indels.hg38.vcf -resource:dbsnp,known=true,training=false,truth=false,prior=2.0 ' + args.ref + '/Homo_sapiens_assembly38.dbsnp.vcf -an DP -an QD -an MQ -an MQRankSum -an ReadPosRankSum -an FS -an SOR -mode INDEL -tranche 100.0 -tranche 99.9 -tranche 99.0 -tranche 90.0 --maxGaussians 4 -recalFile ' + fileName + '_recalibrate_INDEL.recal -tranchesFile ' + fileName + '_recalibrate_INDEL.tranches'
runProcess(command)

#Apply the desired level of recalibration to the Indels in the call set
command = 'java -Xmx3g -jar ' + args.gatk + ' -T ApplyRecalibration  -R ' + args.ref + '/Homo_sapiens_assembly38.fasta -input ' + fileName + '_recalibrated_snps_raw_indels.vcf -mode INDEL --ts_filter_level 99.0 -recalFile ' + fileName + '_recalibrate_INDEL.recal -tranchesFile ' + fileName + '_recalibrate_INDEL.tranches -o ' + fileName + '_recalibrated_variants.vcf'
runProcess(command)

print 'ok'
